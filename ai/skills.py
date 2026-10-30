# SPDX-License-Identifier: Apache-2.0
"""Skill: gói kiến thức QA dạng văn bản mà agent đọc trước khi làm việc.

Thay vì tự huấn luyện mô hình (cần GPU, nhiều dữ liệu, nhiều tuần), TestPilot đưa kiến thức vào
ngữ cảnh của LLM mỗi lần gọi. Có ba nguồn, xếp theo độ ưu tiên khi cắt ngắn:
  1. Bài học đã được người duyệt (bảng lessons), rút ra từ kết quả chạy thật trên chính hệ thống đó.
  2. Skill do nhóm tự viết trên giao diện (bảng skills).
  3. Skill có sẵn trong ai/skills/*.md.

Skill được chọn theo agent và từ khoá xuất hiện trong yêu cầu, nên mỗi lần gọi chỉ tốn token cho phần liên quan.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

SKILL_DIR = Path(__file__).parent / "skills"
AGENTS = ("writer", "explorer", "reviewer", "security", "performance", "triage")
MAX_CONTEXT = 6000


@dataclass
class Skill:
    id: str
    name: str
    description: str = ""
    agents: list[str] = field(default_factory=list)
    triggers: list[str] = field(default_factory=list)   # rỗng = luôn dùng cho các agent đã khai báo
    body: str = ""
    version: str = "1.0"
    builtin: bool = True
    enabled: bool = True

    def public(self) -> dict:
        return asdict(self)


def _list(value: str) -> list[str]:
    return [x.strip() for x in value.strip().strip("[]").split(",") if x.strip()]


def parse(text: str, skill_id: str) -> Skill:
    """Đọc phần đầu `--- key: value ---` và thân skill."""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.S)
    meta, body = {}, text
    if m:
        body = m.group(2)
        for line in m.group(1).splitlines():
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip()
    return Skill(id=meta.get("id", skill_id), name=meta.get("name", skill_id),
                 description=meta.get("description", ""), agents=_list(meta.get("agents", "")),
                 triggers=_list(meta.get("triggers", "")), body=body.strip(), version=meta.get("version", "1.0"))


def builtin_skills() -> list[Skill]:
    return [parse(p.read_text(encoding="utf-8"), p.stem) for p in sorted(SKILL_DIR.glob("*.md"))]


def _conn():
    from backend.db import get_conn
    return get_conn()


def all_skills() -> list[Skill]:
    skills = {s.id: s for s in builtin_skills()}
    try:
        conn = _conn()
        rows = conn.execute("SELECT * FROM skills").fetchall()
        conn.close()
    except Exception:
        return list(skills.values())       # chưa có DB (dùng module AI độc lập): chỉ dùng skill có sẵn
    for r in rows:
        if r["builtin"]:
            if r["id"] in skills:
                skills[r["id"]].enabled = bool(r["enabled"])
        else:
            skills[r["id"]] = Skill(id=r["id"], name=r["name"], description=r["description"] or "",
                                    agents=json.loads(r["agents_json"] or "[]"),
                                    triggers=json.loads(r["triggers_json"] or "[]"), body=r["body"] or "",
                                    version=r["version"] or "1.0", builtin=False, enabled=bool(r["enabled"]))
    return list(skills.values())


def select(agent: str, text: str = "") -> list[Skill]:
    low = (text or "").lower()
    return [s for s in all_skills() if s.enabled and agent in s.agents
            and (not s.triggers or any(t.lower() in low for t in s.triggers))]


def active_lessons(agent: str, host: str | None = None, limit: int = 12) -> list[dict]:
    """Bài học đã duyệt: của đúng hệ thống đó hoặc dùng chung (host rỗng), mới nhất trước."""
    try:
        conn = _conn()
        rows = conn.execute("SELECT id, text FROM lessons WHERE status='active' AND agent=? "
                            "AND (host IS NULL OR host='' OR host=?) ORDER BY id DESC LIMIT ?",
                            (agent, host or "", limit)).fetchall()
        if rows:
            conn.execute(f"UPDATE lessons SET uses=uses+1 WHERE id IN ({','.join('?' * len(rows))})",
                         [r["id"] for r in rows])
            conn.commit()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def context(agent: str, text: str = "", host: str | None = None, limit: int = MAX_CONTEXT) -> tuple[str, list[str], int]:
    """Trả về (đoạn đưa vào prompt, id các skill đã dùng, số bài học đã dùng)."""
    parts, used = [], []
    lessons = active_lessons(agent, host)
    if lessons:
        parts.append("Lessons learned from real runs on this system (follow them):\n"
                     + "\n".join(f"- {x['text']}" for x in lessons))
    room = limit - sum(len(p) for p in parts)
    for s in select(agent, text):
        if len(s.body) > room:
            continue
        parts.append(f"Skill: {s.name}\n{s.body}")
        used.append(s.id)
        room -= len(s.body)
    return ("\n\n".join(parts), used, len(lessons)) if parts else ("", [], 0)


def slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s[:50] or "skill"

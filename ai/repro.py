# SPDX-License-Identifier: Apache-2.0
"""Bước tái hiện dễ đọc từ test case JSON: để dev làm theo bằng tay khi kết quả không đạt."""

from __future__ import annotations

import json
import shlex

from ai.quick_runner import redact
from backend.models import Step, TestCase

_UI = {"click": "Nhấn vào {t}", "fill": 'Nhập "{v}" vào {t}', "select": 'Chọn "{v}" ở {t}', "press": "Nhấn phím {v}",
       "wait_for": "Chờ {t} xuất hiện", "assert_visible": "Kiểm tra {t} đang hiển thị",
       "assert_text": 'Kiểm tra {t} có nội dung "{e}"'}


def _target(s: Step) -> str:
    t = s.target
    if not t:
        return "trang"
    if t.testid:
        return f'phần tử testid "{t.testid}"'
    if t.name:
        return f'{t.role or "phần tử"} "{t.name}"'
    return f"phần tử {t.css}" if t.css else "trang"


def _expect(s: Step) -> str:
    e = s.expect if isinstance(s.expect, dict) else {}
    parts = []
    if e.get("status"):
        parts.append(f"HTTP {e['status']}")
    if e.get("status_in"):
        parts.append("HTTP " + "/".join(map(str, e["status_in"])))
    if e.get("status_lt"):
        parts.append(f"HTTP dưới {e['status_lt']}")
    if e.get("json_contains"):
        parts.append("nội dung chứa " + json.dumps(redact(e["json_contains"]), ensure_ascii=False))
    if e.get("max_ms"):
        parts.append(f"trong {e['max_ms']}ms")
    if e.get("headers"):
        parts.append("có header " + ", ".join(e["headers"]))
    if e.get("cookie_flags"):
        parts.append("cookie có " + ", ".join(e["cookie_flags"]))
    if s.perf:
        p = s.perf
        parts.append(f"{p.get('requests', 20)} request, {p.get('concurrency', 5)} luồng"
                     + (f", p95 dưới {p['p95_ms']}ms" if p.get("p95_ms") else ""))
    return "; ".join(parts)


def describe(s: Step) -> str:
    if s.method:
        body = f" với dữ liệu {json.dumps(redact(s.body), ensure_ascii=False)}" if s.body else ""
        exp = _expect(s)
        return f"Gửi {s.method} {s.path}{body}" + (f" → mong đợi {exp}" if exp else "")
    if s.action == "goto":
        return f"Mở trang {s.url}"
    tpl = _UI.get(s.action or "", "{t}")
    return tpl.format(t=_target(s), v=s.value or "", e=s.expect or s.value or "")


def steps_text(tc: TestCase) -> list[str]:
    return [f"{i}. {describe(s)}" for i, s in enumerate(tc.steps, 1)]


def curl(result: dict, base: str) -> str | None:
    """Lệnh curl của request bị lỗi (body đã che mật khẩu)."""
    req = result.get("request") or {}
    if result.get("type") == "ui" or not req.get("path"):
        return None
    cmd = f"curl -i -X {req.get('method', 'GET')} {shlex.quote(base.rstrip('/') + req['path'])}"
    if req.get("body"):
        cmd += " -H 'Content-Type: application/json' -d " + shlex.quote(json.dumps(req["body"], ensure_ascii=False))
    return cmd

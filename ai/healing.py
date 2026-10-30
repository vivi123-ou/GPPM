# SPDX-License-Identifier: Apache-2.0
"""Self-healing: locator hỏng → đề xuất locator mới từ DOM mới.

1. Rút DOM mới thành danh sách phần tử ứng viên.
2. Xếp hạng ứng viên bằng độ giống (difflib) với target cũ.
3. Gửi top ứng viên cho AI chọn + giải thích; chỉ chấp nhận ứng viên có thật trong DOM.
4. AI lỗi → dùng ứng viên giống nhất nếu đủ điểm.
Kết quả là ĐỀ XUẤT; người dùng duyệt (Chấp nhận/Từ chối) trên dashboard.
"""

from __future__ import annotations

import json
from difflib import SequenceMatcher

from ai import prompts
from ai.dom import Element, extract_elements, looks_like_html
from ai.llm_provider import LLMProvider, get_provider

TOP_K = 25
FALLBACK_MIN_SCORE = 0.55
AI_MIN_CONFIDENCE = 0.5      # AI không chắc thì không đề xuất: thà báo lỗi còn hơn bấm nhầm phần tử

_ACTION_ROLES = {"fill": {"textbox", "searchbox", "spinbutton"},
                 "select": {"combobox", "listbox"},
                 "click": {"button", "link", "checkbox", "radio", "tab", "menuitem"}}


def suggest_locator(step: dict, dom_snapshot: str, provider: LLMProvider | None = None) -> dict:
    """Trả về {"target": {testid, role, name, css} | None, "reason": str, "confidence": float}."""
    step = step.model_dump(exclude_none=True) if hasattr(step, "model_dump") else dict(step)
    old = step.get("target") or {}
    if hasattr(old, "model_dump"):
        old = old.model_dump()
    if not looks_like_html(dom_snapshot):
        return _ai_on_raw(step, dom_snapshot, provider)

    elements = extract_elements(dom_snapshot, limit=400)
    if not elements:
        return _none("DOM mới không có phần tử tương tác nào.")
    ranked = sorted(((score(old, e, step.get("action")), e) for e in elements),
                    key=lambda x: x[0], reverse=True)[:TOP_K]
    candidates = [e for _, e in ranked]

    try:
        llm = provider or get_provider()
        lines = "\n".join(f"[{i}] {e.describe()}" for i, e in enumerate(candidates))
        data = llm.complete_json(prompts.HEAL_SYSTEM, prompts.HEAL_USER.format(
            step=json.dumps(step, ensure_ascii=False), candidates=lines))
        idx = int(data.get("index", -1))
        if 0 <= idx < len(candidates):
            confidence = _clamp(data.get("confidence"), 0.7)
            if confidence < AI_MIN_CONFIDENCE:
                return _none(f"AI không đủ chắc chắn ({confidence:.2f}): {data.get('reason') or ''}")
            return {"target": candidates[idx].target(),
                    "reason": str(data.get("reason") or ""),
                    "confidence": confidence,
                    "source": "ai"}
        return _none(str(data.get("reason") or "AI không tìm thấy phần tử tương ứng."))
    except Exception as e:
        best_score, best = ranked[0]
        if best_score >= FALLBACK_MIN_SCORE:
            return {"target": best.target(),
                    "reason": f"Chọn phần tử giống nhất ({best.describe()}), điểm {best_score:.2f}.",
                    "confidence": round(best_score * 0.8, 2),
                    "source": "fuzzy", "ai_error": str(e)[:200]}
        return _none(f"Không tìm được phần tử đủ giống (AI lỗi: {str(e)[:120]}).")


def score(old: dict, el: Element, action: str | None = None) -> float:
    """Độ giống giữa target cũ và phần tử mới, 0..1."""
    s = 0.0
    if old.get("testid") and el.testid:
        s = max(s, _sim(old["testid"], el.testid))
        if old["testid"] == el.testid:
            return 1.0
    if old.get("name") and el.name:
        name_sim = _sim(old["name"], el.name)
        if old["name"].lower() in el.name.lower() or el.name.lower() in old["name"].lower():
            name_sim = max(name_sim, 0.8)
        s = max(s, name_sim)
    if old.get("css") and (el.id or el.testid):
        s = max(s, 0.6 * _sim(old["css"].lstrip("#."), el.id or el.testid or ""))
    if old.get("role") and el.role == old["role"]:
        s += 0.15
    elif action in _ACTION_ROLES and el.role in _ACTION_ROLES[action]:
        s += 0.1
    return min(s, 1.0)


def _sim(a: str, b: str) -> float:
    a, b = a.lower().replace("-", " ").replace("_", " "), b.lower().replace("-", " ").replace("_", " ")
    return SequenceMatcher(None, a, b).ratio()


def _ai_on_raw(step: dict, snapshot: str, provider) -> dict:
    """Snapshot là accessibility tree dạng text: để AI tự đề xuất target."""
    try:
        llm = provider or get_provider()
        system = prompts.HEAL_SYSTEM.replace(
            'Respond with JSON: {"index": <candidate index or -1>, ',
            'Respond with JSON: {"target": {"testid": null, "role": "...", "name": "..."} or null, ')
        data = llm.complete_json(system, prompts.HEAL_USER.format(
            step=json.dumps(step, ensure_ascii=False), candidates=snapshot[:12000]))
        t = data.get("target")
        if isinstance(t, dict) and any(t.get(k) for k in ("testid", "role", "name", "css")):
            return {"target": {k: t.get(k) or None for k in ("testid", "role", "name", "css")},
                    "reason": str(data.get("reason") or ""),
                    "confidence": _clamp(data.get("confidence"), 0.6), "source": "ai"}
        return _none(str(data.get("reason") or "AI không tìm thấy phần tử tương ứng."))
    except Exception as e:
        return _none(f"AI lỗi: {str(e)[:200]}")


def _none(reason: str) -> dict:
    return {"target": None, "reason": reason, "confidence": 0.0}


def _clamp(v, default):
    try:
        return max(0.0, min(1.0, float(v)))
    except (TypeError, ValueError):
        return default

# SPDX-License-Identifier: Apache-2.0
"""So sánh yêu cầu cũ và mới → đánh dấu test case bị ảnh hưởng."""

from __future__ import annotations

from difflib import unified_diff

from ai import prompts
from ai.llm_provider import LLMProvider, get_provider
from backend.models import TestCase


def find_affected_tests(old_text: str, new_text: str, test_cases: list[TestCase | dict],
                        provider: LLMProvider | None = None) -> dict:
    """Trả về {"affected": [{id, action: update|obsolete, reason}], "uncovered": [str]}."""
    if old_text.strip() == new_text.strip():
        return {"affected": [], "uncovered": []}
    diff = "\n".join(unified_diff(old_text.splitlines(), new_text.splitlines(), lineterm="", n=1))
    tcs = [t if isinstance(t, dict) else t.model_dump() for t in test_cases]
    ids = {t["id"] for t in tcs}
    tests = "\n".join(f"{t['id']}: {t.get('title', '')} ({t.get('type', '')})" for t in tcs)

    llm = provider or get_provider()
    data = llm.complete_json(prompts.IMPACT_SYSTEM, prompts.IMPACT_USER.format(
        diff=diff[:6000], new_text=new_text[:4000], tests=tests[:6000]))
    affected = []
    for a in (data.get("affected") or []) if isinstance(data, dict) else []:
        if isinstance(a, dict) and a.get("id") in ids:
            action = a.get("action") if a.get("action") in ("update", "obsolete") else "update"
            affected.append({"id": a["id"], "action": action, "reason": str(a.get("reason", ""))})
    uncovered = [str(u) for u in (data.get("uncovered") or [])] if isinstance(data, dict) else []
    return {"affected": affected, "uncovered": uncovered}

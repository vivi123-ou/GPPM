# SPDX-License-Identifier: Apache-2.0
"""Accessibility tree / DOM của trang → các bước UI dạng JSON."""

from __future__ import annotations

from ai import prompts
from ai.dom import page_context
from ai.json_utils import unwrap_list
from ai.llm_provider import LLMProvider, get_provider
from ai.test_generator import normalize
from backend.models import Step


def generate_ui_steps(goal: str, accessibility_tree: str, url: str = "/",
                      provider: LLMProvider | None = None) -> list[Step]:
    """accessibility_tree: HTML (page.content()) hoặc aria snapshot
    (page.locator('body').aria_snapshot()) — cả hai đều được."""
    llm = provider or get_provider()
    user = prompts.UI_STEPS_USER.format(goal=goal, url=url, elements=page_context(accessibility_tree))
    raw = unwrap_list(llm.complete_json(prompts.UI_STEPS_SYSTEM, user), "steps")
    steps = normalize({"type": "ui", "steps": raw})["steps"]
    out = [Step.model_validate(s) for s in steps if s.get("action")]
    if out and out[0].action != "goto":
        out.insert(0, Step(action="goto", url=url))
    return out

# SPDX-License-Identifier: Apache-2.0
"""Bóc JSON ra khỏi câu trả lời của LLM (có thể kèm ```json ...``` hoặc lời dẫn)."""

from __future__ import annotations

import json
import re

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S | re.I)


def parse_json(text: str):
    text = (text or "").strip()
    if not text:
        raise ValueError("chuỗi rỗng")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = _FENCE.search(text)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass
    # Lấy khối {...} hoặc [...] ngoài cùng
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        start, end = text.find(open_ch), text.rfind(close_ch)
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError(f"không parse được JSON: {text[:200]!r}")


def unwrap_list(data, *keys: str) -> list:
    """LLM ở JSON mode thường bọc mảng trong object: {"test_cases": [...]}. Lấy mảng ra."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in keys:
            if isinstance(data.get(k), list):
                return data[k]
        for v in data.values():
            if isinstance(v, list):
                return v
    raise ValueError("không tìm thấy mảng trong câu trả lời của AI")

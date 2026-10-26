# SPDX-License-Identifier: Apache-2.0
"""Rút gọn DOM thành danh sách phần tử tương tác (testid, role, name...).

Gửi nguyên DOM cho LLM vừa tốn token vừa dễ nhiễu; danh sách gọn này dùng
cho cả sinh bước UI, Autopilot và self-healing. Chỉ dùng thư viện chuẩn.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
         "meta", "source", "track", "wbr"}
_SKIP = {"script", "style", "noscript", "template", "svg", "head"}
_INTERACTIVE = {"a", "button", "input", "select", "textarea"}
_TEXT_ROLES_TAGS = {"h1", "h2", "h3", "h4", "label"}
_INPUT_ROLES = {"checkbox": "checkbox", "radio": "radio", "submit": "button",
                "button": "button", "reset": "button", "range": "slider",
                "number": "spinbutton", "search": "searchbox"}


@dataclass
class Element:
    tag: str
    role: str | None = None
    name: str = ""
    testid: str | None = None
    id: str | None = None
    attrs: dict = field(default_factory=dict)

    def target(self) -> dict:
        """Chuyển thành Target theo schema chung."""
        return {"testid": self.testid,
                "role": self.role if self.name else None,
                "name": self.name or None,
                "css": None if (self.testid or self.name) else self.css()}

    def css(self) -> str | None:
        if self.id:
            return f"#{self.id}"
        if self.attrs.get("name"):
            return f'{self.tag}[name="{self.attrs["name"]}"]'
        return None

    def describe(self) -> str:
        parts = [self.role or self.tag]
        if self.name:
            parts.append(f'"{self.name}"')
        if self.testid:
            parts.append(f"testid={self.testid}")
        for k in ("type", "placeholder", "href", "name"):
            if self.attrs.get(k):
                parts.append(f"{k}={self.attrs[k]}")
        return " ".join(parts)


def _implicit_role(tag: str, attrs: dict) -> str | None:
    if attrs.get("role"):
        return attrs["role"]
    if tag == "button":
        return "button"
    if tag == "a":
        return "link" if attrs.get("href") is not None else None
    if tag == "input":
        return _INPUT_ROLES.get((attrs.get("type") or "text").lower(), "textbox")
    if tag == "textarea":
        return "textbox"
    if tag == "select":
        return "combobox"
    if tag in ("h1", "h2", "h3", "h4"):
        return "heading"
    return None


class _Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.elements: list[Element] = []
        self.labels_for: dict[str, str] = {}
        self._stack: list[tuple[str, Element | None, list[str], str | None]] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs_list):
        attrs = {k: (v if v is not None else "") for k, v in attrs_list}
        if tag in _SKIP:
            self._skip += 1
            return
        if self._skip:
            return
        el = None
        if (tag in _INTERACTIVE or tag in _TEXT_ROLES_TAGS or "data-testid" in attrs
                or attrs.get("role")):
            if attrs.get("type", "").lower() != "hidden":
                el = Element(tag=tag, role=_implicit_role(tag, attrs),
                             testid=attrs.get("data-testid") or None,
                             id=attrs.get("id") or None, attrs=attrs)
                self.elements.append(el)
        if tag in _VOID:
            if el is not None:
                el.name = _clean(attrs.get("aria-label") or attrs.get("placeholder")
                                 or attrs.get("value") or attrs.get("title") or attrs.get("alt") or "")
            return
        self._stack.append((tag, el, [], attrs.get("for") if tag == "label" else None))

    def handle_endtag(self, tag):
        if tag in _SKIP:
            self._skip = max(0, self._skip - 1)
            return
        if self._skip or tag in _VOID:
            return
        # Đóng tới đúng thẻ (HTML thực tế hay thiếu thẻ đóng)
        while self._stack:
            t, el, texts, label_for = self._stack.pop()
            text = _clean(" ".join(texts))
            if el is not None and not el.name:
                el.name = _clean(el.attrs.get("aria-label") or text or el.attrs.get("title") or "")
            if label_for:
                self.labels_for[label_for] = text
            if self._stack:
                self._stack[-1][2].append(text)
            if t == tag:
                break

    def handle_data(self, data):
        if not self._skip and self._stack and data.strip():
            self._stack[-1][2].append(data)


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()[:80]


def extract_elements(html: str, limit: int = 150) -> list[Element]:
    p = _Parser()
    p.feed(html or "")
    p.close()
    for el in p.elements:
        # input không có tên → lấy từ <label for=id>
        if el.tag in ("input", "select", "textarea") and el.id and el.id in p.labels_for:
            if not el.attrs.get("aria-label"):
                el.name = p.labels_for[el.id] or el.name
    # Bỏ label/heading trùng lặp vô nghĩa, giữ thứ tự
    out = [e for e in p.elements if e.tag != "label" and (e.name or e.testid or e.css())]
    return out[:limit]


def looks_like_html(text: str) -> bool:
    return bool(re.search(r"<\s*(html|body|div|button|input|a|form|main|section)\b", text or "", re.I))


def format_elements(elements: list[Element]) -> str:
    return "\n".join(f"[{i}] {e.describe()}" for i, e in enumerate(elements)) or "(không có phần tử)"


def page_context(snapshot: str, limit: int = 150) -> str:
    """Nhận HTML hoặc accessibility tree (text/YAML) và trả về chuỗi gọn để đưa vào prompt."""
    if looks_like_html(snapshot):
        return format_elements(extract_elements(snapshot, limit))
    return (snapshot or "")[:12000]

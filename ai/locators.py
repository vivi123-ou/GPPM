# SPDX-License-Identifier: Apache-2.0
"""Phân tích locator của một trang: DOM → phần tử → locator đề xuất + độ ổn định.

Mức ổn định dựa trên việc locator phụ thuộc vào thứ gì: testid do dev đặt riêng cho kiểm thử ổn định nhất;
role + tên phụ thuộc nội dung; css bám vào cấu trúc nên dễ gãy nhất. Locator chỉ dùng được khi khớp đúng 1 phần tử,
nên mỗi locator được đếm số khớp trên DOM thật.
"""

from __future__ import annotations

import re

from ai.dom import Element, extract_elements

_GENERATED = re.compile(r"\d{3,}|[a-f0-9]{8,}|^(ember|ext-|ng-|react-|mui-|radix-|:r)", re.I)

GUIDE = [("testid", 100, "Thuộc tính dành riêng cho kiểm thử; không đổi khi đổi giao diện."),
         ("id", 85, "Ổn định nếu không phải id sinh tự động."),
         ("role + tên", 75, "Theo cách người dùng nhìn thấy; đổi khi đổi nội dung chữ."),
         ("label / placeholder", 60, "Cho ô nhập; đổi khi đổi nội dung chữ."),
         ("văn bản", 45, "Dễ trùng và đổi theo nội dung."),
         ("css", 30, "Bám cấu trúc DOM, gãy khi đổi bố cục.")]


def candidates_of(el: Element) -> list[tuple[str, int, str]]:
    """(loại, điểm, biểu thức Playwright) cho một phần tử."""
    out: list[tuple[str, int, str]] = []
    if el.testid:
        out.append(("testid", 100, f'[data-testid="{el.testid}"]'))
    if el.id:
        out.append(("id", 50 if _GENERATED.search(el.id) else 85, f"#{el.id}"))
    if el.role and el.name:
        out.append(("role + tên", 75, f'role={el.role}[name="{_q(el.name)}"]'))
    if el.tag in ("input", "textarea", "select") and el.attrs.get("placeholder"):
        out.append(("label / placeholder", 60, f'[placeholder="{_q(el.attrs["placeholder"])}"]'))
    if el.name and el.tag in ("a", "button"):
        out.append(("văn bản", 45, f'text="{_q(el.name)}"'))
    css = el.css()
    if css and not el.id:
        out.append(("css", 30, css))
    return out


def _q(s: str) -> str:
    return s.replace('"', '\\"')


def inspect_elements(html: str, count_fn=None, limit: int = 80) -> list[dict]:
    """count_fn(selector) → số phần tử khớp trên trang thật; None thì bỏ qua bước đếm."""
    rows = []
    for el in extract_elements(html, limit=limit):
        if el.tag in ("h1", "h2", "h3", "h4") and not el.testid:
            continue
        cands = []
        for kind, score, sel in candidates_of(el):
            matches = None
            if count_fn:
                try:
                    matches = count_fn(sel)
                except Exception:
                    matches = None
            final = score if matches in (None, 1) else (0 if matches == 0 else max(10, score - 40))
            cands.append({"kind": kind, "selector": sel, "matches": matches, "score": final})
        if not cands:
            continue
        best = max(cands, key=lambda c: c["score"])
        rows.append({"tag": el.tag, "role": el.role, "name": el.name, "best": best, "candidates": cands})
    return rows


def summarize(rows: list[dict]) -> dict:
    n = len(rows)
    stable = sum(r["best"]["score"] >= 75 for r in rows)
    weak = [r for r in rows if r["best"]["score"] < 60]
    return {"elements": n, "stable": stable, "stable_pct": round(stable / n * 100) if n else 0, "weak": len(weak),
            "with_testid": sum(any(c["kind"] == "testid" for c in r["candidates"]) for r in rows),
            "advice": ("Trang dễ tự động hoá: đa số phần tử có locator ổn định." if n and stable / n >= .8 else
                       "Nên bổ sung data-testid cho các phần tử có điểm thấp để kịch bản bền hơn.")}


def inspect_page(url: str, timeout_ms: int = 20000) -> dict:
    """Mở trang bằng Playwright, trả về danh sách locator, thống kê và cây accessibility."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 800}, locale="vi-VN")
            page.goto(url, wait_until="load", timeout=timeout_ms)
            try:
                page.wait_for_load_state("networkidle", timeout=3000)
            except Exception:
                pass
            html = page.content()
            rows = inspect_elements(html, lambda sel: page.locator(sel).count())
            try:
                aria = page.locator("body").aria_snapshot(timeout=3000)
            except Exception:
                aria = ""
            return {"url": page.url, "title": page.title(), "dom_bytes": len(html), "summary": summarize(rows),
                    "rows": rows, "aria": aria[:6000], "guide": [{"kind": k, "score": s, "note": n} for k, s, n in GUIDE]}
        finally:
            browser.close()

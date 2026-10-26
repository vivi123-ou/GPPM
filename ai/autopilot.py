# SPDX-License-Identifier: Apache-2.0
"""Autopilot: chỉ cần URL → AI tự khám phá web và sinh test.

- Tìm OpenAPI spec (/openapi.json, ...) → sinh test API.
- Duyệt các trang cùng domain bằng Playwright → rút phần tử → sinh test UI.
Dùng Playwright sync API: gọi từ hàm `def` (không phải `async def`) của FastAPI.
"""

from __future__ import annotations

from collections import deque
from urllib.parse import urljoin, urlparse

import httpx

from ai import prompts
from ai.dom import extract_elements, format_elements
from ai.json_utils import unwrap_list
from ai.llm_provider import LLMProvider, get_provider
from ai.test_generator import _prefix_for, _validate_all, generate_test_cases, is_excluded
from backend.models import TestCase

OPENAPI_PATHS = ("/openapi.json", "/api/openapi.json", "/swagger.json", "/api-docs", "/v3/api-docs")


def find_openapi(base_url: str, timeout: float = 5.0) -> dict | None:
    for p in OPENAPI_PATHS:
        try:
            r = httpx.get(urljoin(base_url, p), timeout=timeout, follow_redirects=True)
            if r.status_code == 200 and "json" in r.headers.get("content-type", ""):
                data = r.json()
                if isinstance(data, dict) and "paths" in data:
                    return data
        except (httpx.HTTPError, ValueError):
            continue
    return None


def fetch_samples(base_url: str, spec: dict, per_endpoint: int = 1200, timeout: float = 5.0) -> str:
    """Gọi các API GET không tham số (vd. danh sách sản phẩm) để AI biết ID/giá trị có thật."""
    import json
    out = []
    for path, ops in spec.get("paths", {}).items():
        if "get" not in ops or "{" in path or is_excluded(path):
            continue
        try:
            r = httpx.get(urljoin(base_url, path), timeout=timeout)
            if r.status_code == 200 and "json" in r.headers.get("content-type", ""):
                data = r.json()
                if isinstance(data, list):
                    data = data[:5]
                out.append(f"GET {path} ->\n{json.dumps(data, ensure_ascii=False)[:per_endpoint]}")
        except (httpx.HTTPError, ValueError):
            continue
    return "\n".join(out)


def explore(start_url: str, max_pages: int = 6, timeout_ms: int = 10000) -> list[dict]:
    """BFS các trang cùng origin, trả về [{url, path, title, html}]."""
    from playwright.sync_api import sync_playwright   # import muộn: chỉ cần khi dùng Autopilot

    origin = urlparse(start_url)
    seen, queue, pages = set(), deque([start_url]), []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        try:
            while queue and len(pages) < max_pages:
                url = queue.popleft().split("#")[0]
                if url in seen:
                    continue
                seen.add(url)
                try:
                    page.goto(url, timeout=timeout_ms, wait_until="networkidle")
                except Exception:
                    continue
                html = page.content()
                pages.append({"url": page.url, "path": urlparse(page.url).path or "/",
                              "title": page.title(), "html": html})
                for href in page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)"):
                    u = urlparse(href)
                    if u.scheme in ("http", "https") and u.netloc == origin.netloc and href not in seen:
                        queue.append(href)
        finally:
            browser.close()
    return pages


def autopilot(url: str, *, max_pages: int = 6, min_cases: int = 4, max_cases: int = 10,
              provider: LLMProvider | None = None, pages: list[dict] | None = None) -> dict:
    """Trả về {"app_summary", "pages": [{path,title,elements}], "test_cases": [TestCase],
    "openapi_found": bool}. Truyền sẵn `pages` để bỏ qua bước mở trình duyệt."""
    llm = provider or get_provider()
    pages = pages if pages is not None else explore(url, max_pages=max_pages)
    page_infos = []
    for p in pages:
        els = extract_elements(p.get("html", ""), limit=60)
        page_infos.append({"path": p.get("path", "/"), "title": p.get("title", ""),
                           "elements": format_elements(els)})

    test_cases: list[TestCase] = []
    summary = ""
    prefix = _prefix_for("autopilot:" + url)
    if page_infos:
        pages_txt = "\n\n".join(f"## {pi['path']} — {pi['title']}\n{pi['elements']}" for pi in page_infos)
        data = llm.complete_json(prompts.AUTOPILOT_SYSTEM, prompts.AUTOPILOT_USER.format(
            base_url=url, pages=pages_txt[:20000], min_cases=min_cases, max_cases=max_cases))
        summary = str(data.get("app_summary", "")) if isinstance(data, dict) else ""
        cases, _ = _validate_all(unwrap_list(data, "test_cases"))
        test_cases += [c for c in cases if c.type == "ui"]

    spec = find_openapi(url)
    if spec:
        try:
            test_cases += generate_test_cases(
                "Kiểm thử các API trong OpenAPI spec: luồng đúng, dữ liệu sai, thiếu trường, giá trị biên.",
                openapi_spec=spec, sample_data=fetch_samples(url, spec),
                min_cases=min_cases, max_cases=max_cases,
                id_prefix=prefix + "A", provider=llm)
        except Exception:
            pass

    ui_i = 0
    for tc in test_cases:
        if tc.type == "ui":
            ui_i += 1
            tc.id = f"{prefix}U-{ui_i:02d}"
    return {"app_summary": summary, "openapi_found": spec is not None,
            "pages": [{"path": pi["path"], "title": pi["title"]} for pi in page_infos],
            "test_cases": test_cases}

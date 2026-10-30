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
from ai.http import client as _http
from ai.dom import extract_elements, format_elements
from ai.json_utils import unwrap_list
from ai.llm_provider import LLMProvider, get_provider
from ai.test_generator import _prefix_for, _validate_all, generate_test_cases, is_excluded
from backend.models import TestCase

OPENAPI_PATHS = ("/openapi.json", "/api/openapi.json", "/swagger.json", "/api-docs", "/v3/api-docs",
                 "/api/v3/openapi.json", "/v2/swagger.json", "/swagger/v1/swagger.json", "/v2/api-docs",
                 "/api/swagger.json", "/swagger/doc.json", "/api/v1/openapi.json", "/docs/openapi.json")


def find_openapi(base_url: str, timeout: float = 5.0) -> dict | None:
    """Tìm OpenAPI spec của website. base_url có thể là trang bất kỳ hoặc link thẳng tới file .json."""
    candidates = [base_url] if base_url.split("?")[0].endswith(".json") else []
    candidates += [urljoin(base_url, p) for p in OPENAPI_PATHS]
    for u in candidates:
        try:
            r = _http.get(u, timeout=timeout)
            if r.status_code == 200 and "json" in r.headers.get("content-type", ""):
                data = r.json()
                if isinstance(data, dict) and "paths" in data:
                    return data
        except (httpx.HTTPError, ValueError):
            continue
    return None


def api_base(url: str, spec: dict | None) -> str:
    """URL gốc để gọi API: origin + servers[0].url của spec (vd. petstore: /api/v3)."""
    u = urlparse(url)
    origin = f"{u.scheme}://{u.netloc}"
    server = ((spec or {}).get("servers") or [{}])[0].get("url", "")
    if server.startswith("http"):
        return server.rstrip("/")
    return (origin + server).rstrip("/")


def fetch_samples(base_url: str, spec: dict, per_endpoint: int = 1200, timeout: float = 5.0) -> str:
    """Gọi các API GET không tham số (vd. danh sách sản phẩm) để AI biết ID/giá trị có thật."""
    import json
    out = []
    for path, ops in spec.get("paths", {}).items():
        if "get" not in ops or "{" in path or is_excluded(path):
            continue
        if len(out) >= 4:
            break
        try:
            r = _http.get(api_base(base_url, spec) + path, timeout=timeout)
            if r.status_code == 200 and "json" in r.headers.get("content-type", ""):
                data = r.json()
                if isinstance(data, list):
                    data = data[:5]
                out.append(f"GET {path} ->\n{json.dumps(data, ensure_ascii=False)[:per_endpoint]}")
        except (httpx.HTTPError, ValueError):
            continue
    return "\n".join(out)


_SKIP_LINK = ("logout", "log-out", "signout", "sign-out", "dang-xuat", "dangxuat")   # giữ phiên đăng nhập
USER_MARK, PASS_MARK = "__USERNAME__", "__PASSWORD__"


def _settle(page, ms: int = 3000):
    try:
        page.wait_for_load_state("networkidle", timeout=ms)
    except Exception:
        pass


def try_login(page, username: str, password: str) -> dict:
    """Trang có ô mật khẩu → điền tài khoản thử nghiệm và gửi form. Trả về {attempted, success, url}."""
    pw_box = page.locator("input[type=password]:visible")
    if pw_box.count() == 0:
        return {"attempted": False, "success": False, "url": page.url}
    before = page.url
    user_box = page.locator("input:visible:not([type=password]):not([type=hidden]):not([type=checkbox])"
                            ":not([type=radio]):not([type=submit]):not([type=button])").first
    try:
        user_box.fill(username, timeout=5000)
        pw_box.first.fill(password, timeout=5000)
        submit = page.locator("button[type=submit]:visible, input[type=submit]:visible")
        if submit.count():
            submit.first.click(timeout=5000)
        else:
            pw_box.first.press("Enter")
        # Đăng nhập có thể chậm (băm mật khẩu, gọi API rồi mới chuyển trang): chờ tới khi
        # rời trang đăng nhập hoặc ô mật khẩu biến mất, tối đa 12 giây
        for _ in range(48):
            if page.url != before or page.locator("input[type=password]:visible").count() == 0:
                break
            page.wait_for_timeout(250)
        _settle(page, 4000)
    except Exception:
        pass
    success = page.url != before or page.locator("input[type=password]:visible").count() == 0
    return {"attempted": True, "success": success, "url": page.url}


def explore(start_url: str, max_pages: int = 6, timeout_ms: int = 15000,
            login: dict | None = None, extra_paths: list[str] | None = None) -> tuple[list[dict], dict]:
    """BFS các trang cùng origin, trả về ([{url, path, title, html, after_login, links}], thông tin đăng nhập).
    login={"username","password"}: gặp trang đăng nhập thì đăng nhập trước rồi mới khám phá tiếp.
    extra_paths: đường đi người dùng chỉ định, ưu tiên duyệt trước (trang không có link dẫn tới)."""
    from playwright.sync_api import sync_playwright   # import muộn: chỉ cần khi dùng Autopilot

    origin = urlparse(start_url)
    seen, queue, pages = set(), deque([start_url]), []
    for p in extra_paths or []:
        queue.append(urljoin(start_url, p.strip()))
    auth = {"login_page": None, "attempted": False, "success": False}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 800}, locale="vi-VN")
        try:
            while queue and len(pages) < max_pages:
                url = queue.popleft().split("#")[0]
                if url in seen:
                    continue
                seen.add(url)
                try:
                    page.goto(url, timeout=timeout_ms, wait_until="load")   # networkidle dễ treo với SPA
                    _settle(page)
                except Exception:
                    continue
                seen.add(page.url.split("#")[0])
                has_login = page.locator("input[type=password]:visible").count() > 0
                pages.append({"url": page.url, "path": urlparse(page.url).path or "/", "title": page.title(),
                              "html": page.content(), "after_login": auth["success"], "login_form": has_login})
                if has_login and not auth["login_page"]:
                    auth["login_page"] = urlparse(page.url).path or "/"
                    if login and login.get("username") and login.get("password") and not auth["attempted"]:
                        auth.update(try_login(page, login["username"], login["password"]))
                        if auth["success"]:
                            queue.appendleft(page.url)          # khám phá trang sau đăng nhập trước
                            seen.discard(page.url.split("#")[0])
                links = []
                for href in page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)"):
                    u = urlparse(href)
                    if (u.scheme in ("http", "https") and u.netloc == origin.netloc
                            and not any(k in href.lower() for k in _SKIP_LINK)):
                        links.append(u.path or "/")
                        if href not in seen:
                            queue.append(href)
                pages[-1]["links"] = sorted(set(links))
        finally:
            browser.close()
    return pages, auth


def autopilot(url: str, *, max_pages: int = 6, min_cases: int = 4, max_cases: int = 10,
              provider: LLMProvider | None = None, pages: list[dict] | None = None,
              include_api: bool = True, login: dict | None = None, paths: list[str] | None = None,
              flow: str = "", guidance: str = "") -> dict:
    """Trả về {"app_summary", "pages": [{path,title,elements}], "test_cases": [TestCase],
    "openapi_found": bool, "auth": {...}}. Truyền sẵn `pages` để bỏ qua bước mở trình duyệt.

    login={"username","password"}: tài khoản thử nghiệm. Mật khẩu KHÔNG gửi cho AI và KHÔNG lưu vào kịch bản:
    kịch bản giữ dấu __USERNAME__/__PASSWORD__, giá trị thật chỉ được thay vào lúc thực thi.
    paths, flow: "đường đi" người dùng cung cấp: các trang cần duyệt và luồng nghiệp vụ cần kiểm thử."""
    llm = provider or get_provider()
    auth = {"login_page": None, "attempted": False, "success": False}
    if pages is None:
        pages, auth = explore(url, max_pages=max_pages, login=login, extra_paths=paths)
    page_infos = []
    for p in pages:
        els = extract_elements(p.get("html", ""), limit=60)
        tag = " (sau khi đăng nhập)" if p.get("after_login") else ""
        page_infos.append({"path": p.get("path", "/"), "title": (p.get("title", "") + tag),
                           "elements": format_elements(els), "count": len(els), "links": p.get("links", []),
                           "after_login": bool(p.get("after_login")), "login_form": bool(p.get("login_form"))})

    test_cases: list[TestCase] = []
    warnings: list[str] = []
    summary = ""
    prefix = _prefix_for("autopilot:" + url)
    if page_infos:
        pages_txt = "\n\n".join(f"## {pi['path']} — {pi['title']}\n{pi['elements']}" for pi in page_infos)
        hints = (f"\nThe user wants these journeys covered first:\n{flow.strip()}\n" if flow.strip() else "")
        if guidance:
            hints += "\n" + guidance + "\n"
        user = prompts.AUTOPILOT_USER.format(base_url=url, pages=pages_txt[:20000], hints=hints,
                                             min_cases=min_cases, max_cases=max_cases)
        if auth["login_page"]:
            user += "\n\n" + (prompts.AUTOPILOT_LOGIN_OK.format(login_page=auth["login_page"])
                              if auth["success"] else
                              prompts.AUTOPILOT_LOGIN_NONE.format(login_page=auth["login_page"]))
        data = llm.complete_json(prompts.AUTOPILOT_SYSTEM, user)
        summary = str(data.get("app_summary", "")) if isinstance(data, dict) else ""
        cases, errors = _validate_all(_safe_list(data))
        if errors:
            # Giống sinh test từ yêu cầu: cho AI tự sửa một lần các case lệch schema
            try:
                data2 = llm.complete_json(prompts.AUTOPILOT_SYSTEM, user + "\n\n" +
                                          prompts.REPAIR_USER.format(errors="\n".join(errors)))
                cases2, errors2 = _validate_all(_safe_list(data2))
                if len(cases2) >= len(cases):
                    cases, errors = cases2, errors2
                    summary = summary or (str(data2.get("app_summary", "")) if isinstance(data2, dict) else "")
            except Exception as e:
                warnings.append(f"AI sửa lỗi schema thất bại: {e}")
        warnings += [f"Bỏ test lệch schema: {e}" for e in errors]
        test_cases += [c for c in cases if c.type == "ui"]
    if auth["login_page"] and not auth["success"]:
        warnings.append("Website yêu cầu đăng nhập" + (": đăng nhập bằng tài khoản thử nghiệm không thành công"
                        if auth["attempted"] else "; chưa cung cấp tài khoản thử nghiệm nên chỉ khảo sát trang công khai"))

    spec = find_openapi(url)
    if spec and not include_api:
        spec = None
    if spec:
        try:
            test_cases += generate_test_cases(
                "Kiểm thử các API trong OpenAPI spec: luồng đúng, dữ liệu sai, thiếu trường, giá trị biên. "
                "Một số API có thể yêu cầu đăng nhập (401): nếu có API đăng ký/đăng nhập, hãy đăng ký {{$email}} "
                "và đăng nhập trong cùng kịch bản trước khi gọi các API khác.",
                openapi_spec=spec, sample_data=fetch_samples(url, spec),
                min_cases=min_cases, max_cases=max_cases,
                id_prefix=prefix + "A", provider=llm)
        except Exception as e:
            warnings.append(f"Không sinh được test API từ OpenAPI: {e}")

    ui_i = 0
    for tc in test_cases:
        if tc.type == "ui":
            ui_i += 1
            tc.id = f"{prefix}U-{ui_i:02d}"
    return {"app_summary": summary, "openapi_found": spec is not None,
            "pages": [{k: pi[k] for k in ("path", "title", "count", "links", "after_login", "login_form")}
                      for pi in page_infos],
            "test_cases": test_cases, "warnings": warnings, "auth": auth}


def _safe_list(data) -> list:
    try:
        return unwrap_list(data, "test_cases")
    except ValueError:
        return []

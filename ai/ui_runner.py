# SPDX-License-Identifier: Apache-2.0
"""Runner UI tối giản: thực thi các bước UI (JSON) bằng Playwright.

- Tìm phần tử theo thứ tự: testid (data-testid / data-test / data-qa) → role + name → label /
  placeholder (với fill) → nút / liên kết / văn bản → css.
- Lỗi thì chụp ảnh màn hình (JPEG nhỏ, base64) để hiện trong báo cáo.
- Self-healing: không tìm thấy phần tử → gửi DOM mới cho AI đề xuất locator thay thế, thử lại
  ngay; nếu chạy được thì ghi lại bản sửa (người dùng duyệt "Áp dụng").
Dùng Playwright sync API: gọi từ route `def` (threadpool), không gọi trong event loop.
"""

from __future__ import annotations

import base64
import time
from urllib.parse import urljoin, urlparse

from ai.quick_runner import run_variables, substitute
from backend.models import Step, Target, TestCase

STEP_TIMEOUT_MS = 6000


class LocatorNotFound(Exception):
    pass


def _origin(url: str) -> str:
    u = urlparse(url)
    return f"{u.scheme}://{u.netloc}"


def _testid_css(v: str) -> str:
    v = v.replace('"', '\\"')
    return f'[data-testid="{v}"], [data-test="{v}"], [data-qa="{v}"], [id="{v}"]'


def candidates(page, t: Target, action: str | None) -> list:
    c = []
    if t.testid:
        c.append(page.locator(_testid_css(t.testid)))
    if t.role and t.name:
        c.append(page.get_by_role(t.role, name=t.name))
    if t.name:
        if action in ("fill", "select", "press"):
            c += [page.get_by_label(t.name), page.get_by_placeholder(t.name)]
        c += [page.get_by_role("button", name=t.name), page.get_by_role("link", name=t.name),
              page.get_by_text(t.name, exact=True), page.get_by_text(t.name)]
    if t.css:
        c.append(page.locator(t.css))
    return c


def locate(page, t: Target | None, action: str | None, timeout_ms: int = STEP_TIMEOUT_MS):
    """Trả về locator đầu tiên tìm thấy (chờ tối đa timeout_ms cho trang động)."""
    if t is None or not any(t.model_dump().values()):
        raise LocatorNotFound("bước không có target")
    deadline = time.time() + timeout_ms / 1000
    while True:
        for loc in candidates(page, t, action):
            try:
                if loc.count() > 0:
                    visible = loc.locator("visible=true")
                    return visible.first if visible.count() > 0 else loc.first
            except Exception:
                continue
        if time.time() > deadline:
            raise LocatorNotFound(f"không tìm thấy phần tử {t.model_dump(exclude_none=True)}")
        page.wait_for_timeout(250)


def _settle(page):
    try:
        page.wait_for_load_state("networkidle", timeout=3000)
    except Exception:
        pass


def do_step(page, s: Step, base: str, timeout_ms: int = STEP_TIMEOUT_MS) -> str:
    """Thực hiện một bước; trả về mô tả ngắn; lỗi thì raise."""
    a = s.action
    if a == "goto":
        page.goto(urljoin(base + "/", (s.url or "/").lstrip("/")) if not (s.url or "").startswith("http") else s.url,
                  wait_until="load", timeout=20000)
        _settle(page)
        return page.url
    if a == "wait_for" and not (s.target and any(s.target.model_dump().values())):
        page.wait_for_timeout(min(int(s.value or 1000), 10000))
        return "chờ"
    if a in ("assert_text",) and not (s.target and any(s.target.model_dump().values())):
        return _assert_text(page.locator("body"), str(s.expect or s.value or ""), timeout_ms)
    if a == "press" and not (s.target and any(s.target.model_dump().values())):
        page.keyboard.press(s.value or "Enter")
        _settle(page)
        return f"phím {s.value or 'Enter'}"

    loc = locate(page, s.target, a, timeout_ms)
    if a == "click":
        loc.click(timeout=timeout_ms)
        _settle(page)
    elif a == "fill":
        loc.fill(s.value or "", timeout=timeout_ms)
    elif a == "select":
        try:
            loc.select_option(s.value or "", timeout=timeout_ms)
        except Exception:
            loc.select_option(label=s.value or "", timeout=timeout_ms)
    elif a == "press":
        loc.press(s.value or "Enter", timeout=timeout_ms)
        _settle(page)
    elif a == "wait_for" or a == "assert_visible":
        loc.wait_for(state="visible", timeout=timeout_ms)
    elif a == "assert_text":
        return _assert_text(loc, str(s.expect or s.value or ""), timeout_ms)
    else:
        raise ValueError(f"action không hỗ trợ: {a}")
    return "ok"


def _assert_text(loc, expected: str, timeout_ms: int) -> str:
    deadline = time.time() + timeout_ms / 1000
    text = ""
    while time.time() <= deadline:
        try:
            text = loc.inner_text(timeout=1000)
        except Exception:
            text = ""
        if expected.strip().lower() in text.lower():
            return f'thấy "{expected}"'
        time.sleep(0.25)
    raise AssertionError(f'expected text "{expected}", got "{text.strip()[:160]}"')


def _shot(page) -> str | None:
    try:
        return "data:image/jpeg;base64," + base64.b64encode(page.screenshot(type="jpeg", quality=55)).decode()
    except Exception:
        return None


def _describe(s: Step) -> str:
    t = s.target
    if s.action == "goto":
        return s.url or "/"
    if not t:
        return s.value or ""
    return t.testid and f'testid="{t.testid}"' or (t.name and f'{t.role or ""} "{t.name}"'.strip()) or t.css or ""


def run_ui_tests(cases: list[TestCase], base_url: str, *, heal: bool = True, headless: bool = True) -> dict[str, list[dict]]:
    """Chạy nhiều test UI trong một trình duyệt (mỗi lượt một context riêng). Trả về {tc.id: [kết quả]}."""
    from playwright.sync_api import sync_playwright

    out: dict[str, list[dict]] = {}
    base = _origin(base_url)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        try:
            for tc in cases:
                out[tc.id] = [_run_one(browser, tc, ds, base, heal) for ds in (tc.data_sets or [None])]
        finally:
            browser.close()
    return out


def _run_one(browser, tc: TestCase, ds, base: str, heal: bool) -> dict:
    variables = run_variables(ds)
    res: dict = {"data_set": ds.name if ds else "-", "expected": ds.expected if ds else "accept",
                 "status": "passed", "error_msg": "", "steps": []}
    ctx = browser.new_context(viewport={"width": 1280, "height": 800}, locale="vi-VN")
    page = ctx.new_page()
    page.set_default_timeout(STEP_TIMEOUT_MS)
    t0 = time.perf_counter()
    try:
        for i, raw in enumerate(tc.steps):
            s = Step.model_validate(substitute(raw.model_dump(), variables))
            res.update(step=i, request={"method": (s.action or "").upper(), "path": _describe(s)})
            try:
                detail = do_step(page, s, base)
                res["steps"].append({"i": i, "action": s.action, "status": "passed", "detail": detail})
            except LocatorNotFound as e:
                fixed = _try_heal(page, raw, s, base) if heal else None
                if fixed:
                    res.setdefault("healings", []).append({**fixed, "step_idx": i})
                    res["steps"].append({"i": i, "action": s.action, "status": "healed", "detail": fixed["reason"]})
                    continue      # chạy tiếp các bước sau bằng locator đã sửa
                res["steps"].append({"i": i, "action": s.action, "status": "failed", "detail": str(e)})
                res.update(status="failed", error_msg=f"waiting for locator: {e}")
                break
            except Exception as e:
                msg = str(e).splitlines()[0][:300]
                res["steps"].append({"i": i, "action": s.action, "status": "failed", "detail": msg})
                res.update(status="failed", error_msg=msg)
                break
        if res.get("healings") and res["status"] == "passed":
            # Chạy được nhờ locator mới → vẫn báo "không đạt" để người dùng duyệt bản sửa
            res.update(status="failed", error_msg="Locator cũ không còn khớp; locator đề xuất đã chạy thành công.")
        if res["status"] == "failed":
            res["screenshot"] = _shot(page)
        res["page_url"] = page.url
    finally:
        res["duration_ms"] = int((time.perf_counter() - t0) * 1000)
        ctx.close()
    return res


def _try_heal(page, raw: Step, s: Step, base: str) -> dict | None:
    """Hỏi AI locator thay thế từ DOM hiện tại, thử ngay; được thì trả về bản sửa."""
    from ai.healing import suggest_locator
    try:
        sug = suggest_locator(s.model_dump(exclude_none=True), page.content())
    except Exception:
        return None
    if not sug.get("target"):
        return None
    new_target = Target.model_validate(sug["target"])
    try:
        do_step(page, s.model_copy(update={"target": new_target}), base)
    except Exception:
        return None
    return {"old_target": raw.target.model_dump(exclude_none=True) if raw.target else None,
            "new_target": new_target.model_dump(exclude_none=True), "reason": sug.get("reason", ""),
            "confidence": sug.get("confidence"), "verified": True}

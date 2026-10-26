"""API của module AI cho web TestPilot (trang AI Lab: /ai.html).

Các route dùng `def` (không async) vì Playwright/httpx sync chạy trong threadpool.
Mọi route nhận `url` tuỳ chọn để test website bất kỳ; bỏ trống = Demo Shop (DEMO_SHOP_URL).
"""
import os

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend import ai_client
from ai.http import client as _http
from backend.db import get_conn
from backend.models import TestCase

router = APIRouter(prefix="/api/ai", tags=["AI"])


def _default_url() -> str:
    return os.getenv("DEMO_SHOP_URL") or "http://127.0.0.1:8000"


def _load_cases(ids: list[str] | None) -> list[TestCase]:
    conn = get_conn()
    rows = conn.execute("SELECT id, json FROM test_cases WHERE status='active' ORDER BY id").fetchall()
    conn.close()
    cases = [TestCase.model_validate_json(r["json"]) for r in rows]
    return [c for c in cases if not ids or c.id in ids]


def _save_cases(cases: list[TestCase], requirement_text: str) -> int:
    conn = get_conn()
    req_id = conn.execute("INSERT INTO requirements(text) VALUES (?)", (requirement_text,)).lastrowid
    for tc in cases:
        tc.requirement_id = f"REQ-{req_id}"
        conn.execute("INSERT OR REPLACE INTO test_cases(id, requirement_id, json, version, status) "
                     "VALUES (?,?,?,1,'active')", (tc.id, tc.requirement_id, tc.model_dump_json()))
    conn.commit()
    conn.close()
    return req_id


@router.get("/config")
def config():
    from ai.llm_provider import FallbackProvider, get_provider
    info = {"use_mock": ai_client.USE_MOCK, "target_url": _default_url()}
    if not ai_client.USE_MOCK:
        try:
            p = get_provider()
            chain = p.providers if isinstance(p, FallbackProvider) else [p]
            info.update(provider=p.name, model=p.model,
                        fallback=[f"{x.name}/{x.model}" for x in chain[1:]],
                        last_used=f"{p.last_used.name}/{p.last_used.model}" if isinstance(p, FallbackProvider) else None)
        except Exception as e:
            info.update(provider_error=str(e))
    return info


@router.get("/inspect")
def inspect(url: str):
    """Kiểm tra nhanh hệ thống mục tiêu: truy cập được không, có OpenAPI không, nên tạo test theo cách nào."""
    import re
    from urllib.parse import urlparse
    from ai.autopilot import api_base, find_openapi
    from ai.test_generator import is_excluded

    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.netloc:
        raise HTTPException(400, "Địa chỉ không hợp lệ. Ví dụ: https://example.com")
    info = {"url": url, "reachable": False, "status": None, "title": "", "openapi_found": False,
            "endpoints": 0, "api_base": None, "demo_shop": url.startswith(_default_url())}
    try:
        r = _http.get(url, timeout=10)
        info.update(reachable=r.status_code < 500, status=r.status_code)
        m = re.search(r"<title[^>]*>(.*?)</title>", r.text, re.I | re.S)
        if m:
            info["title"] = re.sub(r"\s+", " ", m.group(1)).strip()[:120]
        elif "json" in r.headers.get("content-type", ""):
            info["title"] = ((r.json().get("info") or {}).get("title") or "") if isinstance(r.json(), dict) else ""
    except Exception as e:
        info["error"] = str(e)[:200]
    spec = find_openapi(url)
    if spec:
        ops = [(p, m) for p, o in spec.get("paths", {}).items() if not is_excluded(p)
               for m in o if m.lower() in ("get", "post", "put", "patch", "delete")]
        info.update(openapi_found=True, endpoints=len(ops), api_base=api_base(url, spec),
                    title=info["title"] or (spec.get("info") or {}).get("title", ""))
        info["reachable"] = True
    info["recommended"] = "requirement" if info["openapi_found"] else "autopilot"
    info["demo_account"] = _demo_account() if info["demo_shop"] else None
    return info


def _demo_account() -> dict | None:
    """Tài khoản demo của Demo Shop (SHOP_DEMO_EMAIL/PASSWORD trong .env). Chỉ trả email cho giao diện;
    mật khẩu ở lại server và chỉ dùng khi trình duyệt thực thi."""
    email = os.getenv("SHOP_DEMO_EMAIL", "").strip()
    return {"email": email, "available": bool(os.getenv("SHOP_DEMO_PASSWORD"))} if email else None


@router.get("/requirements")
def requirements():
    """Danh sách yêu cầu (để biết test case thuộc hệ thống nào)."""
    conn = get_conn()
    rows = conn.execute("SELECT id, text, created_at FROM requirements ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


class GenerateIn(BaseModel):
    text: str
    url: str | None = None
    count: int | None = Field(default=None, ge=1, le=150)   # None = AI tự chọn (4–10)


@router.post("/generate")
def generate(body: GenerateIn):
    """Yêu cầu + website bất kỳ → AI đọc OpenAPI/dữ liệu của website đó và viết test case."""
    if not body.text.strip():
        raise HTTPException(400, "Yêu cầu không được để trống")
    from ai.autopilot import fetch_samples, find_openapi
    from ai.test_generator import generate_test_cases
    url = body.url or _default_url()
    spec = find_openapi(url)
    try:
        cases = generate_test_cases(body.text, openapi_spec=spec, count=body.count,
                                    sample_data=fetch_samples(url, spec) if spec else None)
    except Exception as e:
        raise HTTPException(502, f"AI lỗi: {e}")
    _save_cases(cases, f"[{url}] {body.text}")
    return {"url": url, "openapi_found": spec is not None, "ids": [c.id for c in cases]}


class RunIn(BaseModel):
    test_case_ids: list[str] | None = None
    url: str | None = None
    classify: bool = True
    reset_shop: bool = True


def _shop_reset_hook(base: str):
    """Chỉ Demo Shop có /api/shop/bugs: đặt lại kho/đơn hàng nhưng GIỮ các bug flag đang bật."""
    try:
        r = _http.get(f"{base}/api/shop/bugs", timeout=5)
        flags = r.json() if r.status_code == 200 else None
    except Exception:
        flags = None
    if not isinstance(flags, dict) or not all(isinstance(v, bool) for v in flags.values()):
        return None

    def before_each():
        _http.post(f"{base}/api/shop/reset", timeout=5)
        for name, on in flags.items():
            if on:
                _http.put(f"{base}/api/shop/bugs/{name}", json={"enabled": True}, timeout=5)
    return before_each


def _target(url: str) -> tuple[str, list[str] | None, str]:
    """(api_base, các path có thật, ngữ cảnh: ràng buộc OpenAPI + dữ liệu thật) của hệ thống đích."""
    from ai.autopilot import api_base, fetch_samples, find_openapi
    from ai.test_generator import summarize_openapi
    spec = find_openapi(url)
    api_paths = list((spec or {}).get("paths", {})) or None
    # Dữ liệu thật + ràng buộc API để AI kiểm lại kỳ vọng của test trước khi kết luận "lỗi ứng dụng"
    context = (summarize_openapi(spec, limit=3000) + "\n\n" + fetch_samples(url, spec)) if spec else ""
    return api_base(url, spec), api_paths, context


def _classify_parallel(failed: list[tuple], api_paths, context) -> list[dict]:
    """Chia lỗi thành lô 6, các lô chạy song song (AI_PARALLEL)."""
    from concurrent.futures import ThreadPoolExecutor
    chunks = [failed[i:i + 6] for i in range(0, len(failed), 6)]
    with ThreadPoolExecutor(max_workers=max(1, int(os.getenv("AI_PARALLEL", "3")))) as pool:
        parts = pool.map(lambda ch: ai_client.classify_failures(ch, api_paths, context), chunks)
    return [v for part in parts for v in part]


@router.post("/run")
def run_tests(body: RunIn):
    """Chạy các test case (API bằng HTTP, UI bằng Playwright) trên website đích.
    classify=true: AI phân loại lỗi luôn trong lượt này; giao diện dùng classify=false để hiện
    kết quả ngay rồi gọi /api/ai/classify sau."""
    from ai.quick_runner import run_api_test
    from ai.ui_runner import run_ui_tests
    url = body.url or _default_url()
    base, api_paths, context = _target(url)

    cases = _load_cases(body.test_case_ids)
    if not cases:
        raise HTTPException(404, "Không có kịch bản nào để thực thi")
    before_each = _shop_reset_hook(base) if body.reset_shop else None

    ui_cases = [c for c in cases if c.type == "ui"]
    if ui_cases and before_each:
        before_each()
    ui_results = run_ui_tests(ui_cases, url) if ui_cases else {}

    out, failed = [], []
    for tc in cases:
        results = ui_results.get(tc.id, []) if tc.type == "ui" else run_api_test(tc, base, before_each=before_each)
        for res in results:
            item = {"test_case_id": tc.id, "title": tc.title, "type": tc.type, **res}
            if res["status"] == "failed" and body.classify:
                failed.append((tc, item))
            out.append(item)

    # Chạy test tuần tự (shop được reset giữa các lượt) nhưng phân loại lỗi theo lô, song song
    for (_, item), verdict in zip(failed, _classify_parallel(failed, api_paths, context)):
        item["ai_analysis"] = verdict
    passed = sum(r["status"] == "passed" for r in out)
    return {"target_url": base, "url": url, "total": len(out), "passed": passed, "failed": len(out) - passed,
            "skipped_ui": [], "results": out}


class HealFix(BaseModel):
    step_idx: int
    new_target: dict


class HealApplyIn(BaseModel):
    test_case_id: str
    step_idx: int | None = None        # một bản sửa
    new_target: dict | None = None
    fixes: list[HealFix] = []          # hoặc nhiều bản sửa cùng lúc


@router.post("/heal/apply")
def heal_apply(body: HealApplyIn):
    """Duyệt bản sửa self-healing: ghi locator mới vào bước tương ứng (tăng version)."""
    from backend.models import Target
    cases = _load_cases([body.test_case_id])
    if not cases:
        raise HTTPException(404, "Không thấy kịch bản")
    tc = cases[0]
    fixes = body.fixes or [HealFix(step_idx=body.step_idx, new_target=body.new_target or {})]
    for f in fixes:
        if not 0 <= f.step_idx < len(tc.steps):
            raise HTTPException(404, f"Không thấy bước {f.step_idx}")
        tc.steps[f.step_idx].target = Target.model_validate(f.new_target)
    conn = get_conn()
    conn.execute("UPDATE test_cases SET json=?, version=version+1 WHERE id=?", (tc.model_dump_json(), tc.id))
    conn.commit()
    conn.close()
    return {"ok": True, "test_case": tc.model_dump(exclude_none=True)}


class ClassifyIn(BaseModel):
    url: str | None = None
    items: list[dict]          # các phần tử "results" (không đạt) lấy từ /api/ai/run


@router.post("/classify")
def classify(body: ClassifyIn):
    """Phân loại một nhóm lỗi (giao diện gọi nhiều nhóm song song sau khi đã hiện kết quả)."""
    _, api_paths, context = _target(body.url or _default_url())
    by_id = {c.id: c for c in _load_cases(list({i.get("test_case_id") for i in body.items}))}
    pairs = [(by_id.get(i.get("test_case_id")) or {"id": i.get("test_case_id"), "type": "api", "steps": []}, i)
             for i in body.items]
    return _classify_parallel(pairs, api_paths, context)


class AutopilotIn(BaseModel):
    url: str | None = None
    save: bool = True
    include_api: bool = True
    username: str | None = None      # tài khoản thử nghiệm (tuỳ chọn) cho website cần đăng nhập
    password: str | None = None
    use_demo_account: bool = False   # Demo Shop: dùng tài khoản demo trong .env (mật khẩu không qua trình duyệt)


@router.post("/autopilot")
def autopilot(body: AutopilotIn):
    """Dán URL → AI tự khám phá trang + OpenAPI và sinh test case."""
    url = body.url or _default_url().rstrip("/") + "/shop"
    try:
        if ai_client.USE_MOCK:
            r = ai_client.autopilot(url)
        else:
            from ai.autopilot import autopilot as real
            login = {"username": body.username, "password": body.password} if body.username and body.password else None
            if body.use_demo_account and os.getenv("SHOP_DEMO_EMAIL") and os.getenv("SHOP_DEMO_PASSWORD"):
                login = {"username": os.getenv("SHOP_DEMO_EMAIL"), "password": os.getenv("SHOP_DEMO_PASSWORD")}
            r = real(url, include_api=body.include_api, login=login)
    except Exception as e:
        raise HTTPException(502, f"Autopilot lỗi: {e}")
    if body.save and r["test_cases"]:
        _save_cases(r["test_cases"], f"[Autopilot] {url}")
    return {**r, "test_cases": [t.model_dump(exclude_none=True) for t in r["test_cases"]]}


@router.post("/test-data/{tc_id}")
def test_data(tc_id: str, save: bool = False):
    """Sinh thêm dữ liệu EP/BVA cho một test case."""
    cases = _load_cases([tc_id])
    if not cases:
        raise HTTPException(404, "Không thấy test case")
    tc = cases[0]
    sets = ai_client.generate_test_data(tc)
    if save:
        tc.data_sets = sets
        conn = get_conn()
        conn.execute("UPDATE test_cases SET json=?, version=version+1 WHERE id=?", (tc.model_dump_json(), tc_id))
        conn.commit()
        conn.close()
    return [s.model_dump() for s in sets]


class HealIn(BaseModel):
    step: dict
    url: str | None = None       # trang để lấy DOM mới (render bằng Playwright)
    dom: str | None = None       # hoặc truyền sẵn HTML


@router.post("/heal")
def heal(body: HealIn):
    """Self-healing: đề xuất locator mới cho bước UI bị hỏng."""
    dom = body.dom
    if not dom:
        from playwright.sync_api import sync_playwright
        url = body.url or _default_url().rstrip("/") + "/shop"
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            page = b.new_page()
            page.goto(url, wait_until="networkidle")
            dom = page.content()
            b.close()
    return ai_client.suggest_locator(body.step, dom)


class ImpactIn(BaseModel):
    old_text: str
    new_text: str


@router.post("/impact")
def impact(body: ImpactIn):
    """So sánh yêu cầu cũ/mới → test case bị ảnh hưởng."""
    cases = [c.model_dump() for c in _load_cases(None)]
    return ai_client.find_affected_tests(body.old_text, body.new_text, cases)

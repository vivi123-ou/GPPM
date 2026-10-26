"""API của module AI cho web TestPilot (trang AI Lab: /ai.html).

Các route dùng `def` (không async) vì Playwright/httpx sync chạy trong threadpool.
Mọi route nhận `url` tuỳ chọn để test website bất kỳ; bỏ trống = Demo Shop (DEMO_SHOP_URL).
"""
import os

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend import ai_client
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


class GenerateIn(BaseModel):
    text: str
    url: str | None = None


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
        cases = generate_test_cases(body.text, openapi_spec=spec,
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
        r = httpx.get(f"{base}/api/shop/bugs", timeout=5)
        flags = r.json() if r.status_code == 200 else None
    except Exception:
        flags = None
    if not isinstance(flags, dict) or not all(isinstance(v, bool) for v in flags.values()):
        return None

    def before_each():
        httpx.post(f"{base}/api/shop/reset", timeout=5)
        for name, on in flags.items():
            if on:
                httpx.put(f"{base}/api/shop/bugs/{name}", json={"enabled": True}, timeout=5)
    return before_each


@router.post("/run")
def run_tests(body: RunIn):
    """Chạy thử các test case API trên website đích, AI phân loại từng lỗi."""
    from ai.autopilot import api_base, find_openapi
    from ai.quick_runner import run_api_test
    url = body.url or _default_url()
    spec = find_openapi(url)
    base = api_base(url, spec)
    api_paths = list((spec or {}).get("paths", {})) or None

    cases = _load_cases(body.test_case_ids)
    skipped_ui = [c.id for c in cases if c.type == "ui"]
    cases = [c for c in cases if c.type == "api"]
    if not cases:
        raise HTTPException(404, "Không có test case API nào để chạy (test UI cần Runner UI)")
    before_each = _shop_reset_hook(base) if body.reset_shop else None

    out = []
    for tc in cases:
        for res in run_api_test(tc, base, before_each=before_each):
            item = {"test_case_id": tc.id, "title": tc.title, **res}
            if res["status"] == "failed" and body.classify:
                item["ai_analysis"] = ai_client.classify_failure(tc, res, api_paths)
            out.append(item)
    passed = sum(r["status"] == "passed" for r in out)
    return {"target_url": base, "total": len(out), "passed": passed, "failed": len(out) - passed,
            "skipped_ui": skipped_ui, "results": out}


class AutopilotIn(BaseModel):
    url: str | None = None
    save: bool = True
    include_api: bool = True


@router.post("/autopilot")
def autopilot(body: AutopilotIn):
    """Dán URL → AI tự khám phá trang + OpenAPI và sinh test case."""
    url = body.url or _default_url().rstrip("/") + "/shop"
    try:
        if ai_client.USE_MOCK:
            r = ai_client.autopilot(url)
        else:
            from ai.autopilot import autopilot as real
            r = real(url, include_api=body.include_api)
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

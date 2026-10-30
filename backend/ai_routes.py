"""API của module AI cho web TestPilot (trang AI Lab: /ai.html).

Các route dùng `def` (không async) vì Playwright/httpx sync chạy trong threadpool.
Mọi route nhận `url` tuỳ chọn để test website bất kỳ; bỏ trống = Demo Shop (DEMO_SHOP_URL).
"""
import json
import os
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from backend import ai_client, jobs, vault
from ai.http import client as _http
from backend.db import get_conn
from backend.models import TestCase
from backend.security import check_target, client_ip, is_local_target

router = APIRouter(prefix="/api/ai", tags=["AI"])


def _default_url() -> str:
    return os.getenv("DEMO_SHOP_URL") or "http://127.0.0.1:8000"


def _load_cases(ids: list[str] | None) -> list[TestCase]:
    """ids=None: toàn bộ. Có danh sách: đúng các kịch bản đó, theo đúng thứ tự, không thêm bớt."""
    conn = get_conn()
    rows = conn.execute("SELECT id, json FROM test_cases WHERE status='active' ORDER BY id").fetchall()
    conn.close()
    cases = {r["id"]: TestCase.model_validate_json(r["json"]) for r in rows}
    if ids is None:
        return list(cases.values())
    return [cases[i] for i in dict.fromkeys(ids) if i in cases]


def _authorized(url: str, flag: bool) -> bool:
    """Bảo mật, hiệu năng, phương thức ghi/xoá chỉ chạy tự do trên hệ thống cục bộ; website bên ngoài cần xác nhận có quyền."""
    return flag or url.startswith(_default_url()) or is_local_target(url)


def _save_snapshot(url: str, spec: dict | None) -> None:
    """Ghi lại danh sách endpoint nếu khác lần trước, để phát hiện API thay đổi sau này."""
    if not spec:
        return
    from ai.test_generator import is_excluded
    eps = sorted(f"{m.upper()} {p}" for p, ops in spec.get("paths", {}).items() if not is_excluded(p)
                 for m in ops if m.lower() in ("get", "post", "put", "patch", "delete"))
    host = urlparse(url).netloc
    conn = get_conn()
    last = conn.execute("SELECT endpoints_json FROM spec_snapshots WHERE host=? ORDER BY id DESC LIMIT 1", (host,)).fetchone()
    if not last or json.loads(last["endpoints_json"]) != eps:
        conn.execute("INSERT INTO spec_snapshots(host, endpoints_json) VALUES (?,?)", (host, json.dumps(eps)))
        conn.commit()
    conn.close()


def _save_agent_run(kind: str, target: str, req_id, trace: list, stats: dict) -> None:
    conn = get_conn()
    conn.execute("INSERT INTO agent_runs(kind, target, requirement_id, trace_json, stats_json) VALUES (?,?,?,?,?)",
                 (kind, target, f"REQ-{req_id}" if req_id else None,
                  json.dumps(trace, ensure_ascii=False), json.dumps(stats, ensure_ascii=False)))
    conn.commit()
    conn.close()


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
def inspect(url: str, request: Request):
    """Kiểm tra nhanh hệ thống mục tiêu: truy cập được không, có OpenAPI không, nên tạo test theo cách nào."""
    import re
    from ai.autopilot import api_base, find_openapi
    from ai.test_generator import is_excluded

    check_target(url, client_ip(request))
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
    info["local"] = is_local_target(url)
    info["has_credentials"] = vault.get(url) is not None
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
    categories: list[str] = ["functional"]                  # functional, security, performance
    authorized: bool = False                                # đã xác nhận có quyền kiểm thử hệ thống đích
    review: bool = True                                     # AI đối chiếu kịch bản với yêu cầu
    auto_fix: bool = True                                   # agent Fixer sửa kịch bản bị chê
    lead: bool = True                                       # agent Lead lập kế hoạch, giao viết thêm phần thiếu
    verify: bool = True                                     # agent Verifier chạy thử kịch bản ngay sau khi sinh
    economy: bool = True                                    # số lượng lớn: AI viết phần lõi, Expander sinh phần còn lại theo luật
    reuse: bool = True                                      # dùng lại câu trả lời AI cho đúng cùng một đầu vào


@router.post("/generate")
def generate(body: GenerateIn, request: Request):
    """Yêu cầu + website bất kỳ → các agent: lập kế hoạch, viết, dò bảo mật/hiệu năng, duyệt, chạy thử, tự sửa."""
    return _generate(body, client_ip(request))


@router.post("/jobs/generate")
def generate_job(body: GenerateIn, request: Request):
    """Như /generate nhưng chạy nền: lấy tiến độ từng agent ở GET /api/ai/jobs/{id}."""
    client = client_ip(request)
    check_target(body.url or _default_url(), client)
    return {"job_id": jobs.start(lambda on_step: _generate(body, client, on_step))}


@router.get("/jobs/{job_id}")
def job_status(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Không thấy việc này (server có thể vừa khởi động lại)")
    return job


def _llm_or_none(reuse: bool = True):
    """LLM cho một lượt làm việc trên giao diện: có giới hạn thời gian chờ, hỏng thì các bước sau không chờ lại."""
    if ai_client.USE_MOCK:
        return None
    from ai.llm_cache import CachedLLM
    from ai.llm_provider import get_provider
    try:
        return CachedLLM(get_provider(), read_cache=reuse)
    except Exception:
        return None


def _make_verifier(url: str, spec: dict | None, samples: str, text: str, credentials: dict | None, llm):
    """Hàm chạy thử gắn với hệ thống đích: giữ các lỗi mô phỏng đang bật, đặt lại dữ liệu giữa các lượt."""
    from ai.autopilot import api_base
    from ai.skills import context as skill_context
    from ai.test_generator import summarize_openapi
    from ai.verifier import verify
    base = api_base(url, spec)
    hook = _shop_reset_hook(base)
    paths = list((spec or {}).get("paths", {})) or None
    ctx = "\n\n".join(p for p in (f"Requirement:\n{text[:2500]}" if text.strip() else "", skill_context("triage", text, urlparse(url).netloc)[0],
                                  summarize_openapi(spec, limit=2500) if spec else "", samples) if p)
    def run(cases):
        with jobs.target_lock(url):
            return verify(cases, url, base, before_each=hook, credentials=credentials, local=is_local_target(url),
                          provider=llm, api_paths=paths, context=ctx)
    return run


def _generate(body: GenerateIn, client: str | None, on_step=None) -> dict:
    if not body.text.strip():
        raise HTTPException(400, "Yêu cầu không được để trống")
    from ai.agents import generate_pipeline
    from ai.autopilot import api_base, fetch_samples, find_openapi
    from ai.expander import fetch_items
    from backend.quality_routes import save_reviews
    url = body.url or _default_url()
    check_target(url, client)
    bad = [c for c in body.categories if c not in ("functional", "security", "performance")]
    if bad or not body.categories:
        raise HTTPException(422, "Nhóm kịch bản phải thuộc: functional, security, performance")
    if set(body.categories) & {"security", "performance"} and not _authorized(url, body.authorized):
        raise HTTPException(403, "Kịch bản bảo mật và hiệu năng chỉ dành cho hệ thống bạn được phép kiểm thử. "
                                 "Hãy xác nhận quyền kiểm thử trước khi tạo.")
    spec = find_openapi(url)
    if _authorized(url, body.authorized) and spec:
        # Dữ liệu sạch trước khi đọc: tồn kho đúng và cùng đầu vào thì dùng lại được câu trả lời AI đã có
        hook = _shop_reset_hook(api_base(url, spec))
        if hook:
            with jobs.target_lock(url):
                hook()
    samples = fetch_samples(url, spec) if spec else ""
    items = fetch_items(url, spec) if spec else []
    _save_snapshot(url, spec)
    seed = [c for c in ai_client.generate_test_cases(body.text)] if ai_client.USE_MOCK and "functional" in body.categories else None
    llm = _llm_or_none(reuse=body.reuse)
    verifier, note = None, ""
    # Không có AI vẫn chạy thử được: kịch bản theo luật không cần AI, lỗi kịch bản khác dùng phân loại bằng luật
    if body.verify and not ai_client.USE_MOCK:
        if _authorized(url, body.authorized):
            verifier = _make_verifier(url, spec, samples, body.text, _credentials(body, url), llm)
        else:
            note = "Bỏ qua chạy thử: chưa xác nhận quyền kiểm thử hệ thống này"
    result = generate_pipeline(body.text, url, count=body.count, categories=body.categories, spec=spec, samples=samples,
                               ai_review_enabled=body.review, auto_fix=body.auto_fix, seed_cases=seed, provider=llm,
                               llm_enabled=llm is not None, lead=body.lead, verifier=verifier, verify_note=note, on_step=on_step,
                               economy=body.economy, items=items)
    cases = result["cases"]
    if not cases:
        raise HTTPException(502, "AI lỗi: " + "; ".join(result["warnings"][:2]))
    req_id = _save_cases(cases, f"[{url}] {body.text}")
    save_reviews(result["reviews"])
    criteria = result["criteria"]
    stats = {**result["stats"], "writer_produced": sum(c.category == "functional" and not (c.technique or "").startswith("rule:") for c in cases),
             "criteria_total": len(criteria), "criteria_covered": sum(bool(c["covered_by"]) for c in criteria)}
    _save_agent_run("generate", url, req_id, result["trace"], stats)
    return {"url": url, "openapi_found": spec is not None, "ids": [c.id for c in cases], "requirement_id": req_id,
            "reviews": result["reviews"], "criteria": criteria, "plan": result["plan"], "stats": stats,
            "trace": result["trace"], "warnings": result["warnings"]}


class RunIn(BaseModel):
    test_case_ids: list[str] | None = None
    url: str | None = None
    classify: bool = True
    reset_shop: bool = True
    authorized: bool = False
    username: str | None = None      # tài khoản thử nghiệm, không ghi vào kịch bản
    password: str | None = None
    use_demo_account: bool = False


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
    from ai.skills import context as skill_context
    guidance = skill_context("triage", "", urlparse(url).netloc)[0]
    return api_base(url, spec), api_paths, f"{guidance}\n\n{context}".strip()


def _classify_parallel(failed: list[tuple], api_paths, context) -> list[dict]:
    """Chia lỗi thành lô 6, các lô chạy song song (AI_PARALLEL)."""
    from concurrent.futures import ThreadPoolExecutor
    chunks = [failed[i:i + 6] for i in range(0, len(failed), 6)]
    with ThreadPoolExecutor(max_workers=max(1, int(os.getenv("AI_PARALLEL", "3")))) as pool:
        parts = pool.map(lambda ch: ai_client.classify_failures(ch, api_paths, context), chunks)
    return [v for part in parts for v in part]


def _credentials(body, url: str) -> dict | None:
    """Tài khoản cho lượt chạy: nhập trực tiếp → đã nhập trong phiên này → tài khoản demo của shop."""
    username, password = getattr(body, "username", None), getattr(body, "password", None)
    if username and password:
        vault.remember(url, username, password)
        return {"username": username, "password": password}
    if vault.get(url):
        return vault.get(url)
    if (getattr(body, "use_demo_account", False) or url.startswith(_default_url())) and os.getenv("SHOP_DEMO_EMAIL") and os.getenv("SHOP_DEMO_PASSWORD"):
        return {"username": os.getenv("SHOP_DEMO_EMAIL"), "password": os.getenv("SHOP_DEMO_PASSWORD")}
    return None


def _save_run(url: str, cases: list[TestCase], out: list[dict], flags: dict | None) -> int:
    """Lưu lượt chạy (không lưu ảnh) để tính số liệu theo thời gian; gắn result_id để phân loại sau ghi lại."""
    conn = get_conn()
    passed = sum(r["status"] == "passed" for r in out)
    run_id = conn.execute("INSERT INTO runs(finished_at, bug_flags_snapshot, summary, target, cases_total) "
                          "VALUES (CURRENT_TIMESTAMP,?,?,?,?)",
                          (json.dumps(flags or {}), json.dumps({"total": len(out), "passed": passed, "failed": len(out) - passed}),
                           url, len(cases))).lastrowid
    for item in out:
        detail = {k: v for k, v in item.items() if k not in ("screenshot", "response_body")}
        item["result_id"] = conn.execute(
            "INSERT INTO results(run_id, test_case_id, data_set, status, error_msg, duration_ms, ai_analysis_json, title, type, category, detail_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, item["test_case_id"], item.get("data_set"), item["status"], item.get("error_msg"), item.get("duration_ms"),
             json.dumps(item["ai_analysis"], ensure_ascii=False) if item.get("ai_analysis") else None, item.get("title"),
             item.get("type"), item.get("category"), json.dumps(detail, ensure_ascii=False, default=str))).lastrowid
        for h in item.get("healings") or []:
            conn.execute("INSERT INTO healing_patches(result_id, test_case_id, step_idx, old_target, new_target, reason) VALUES (?,?,?,?,?,?)",
                         (item["result_id"], item["test_case_id"], h["step_idx"], json.dumps(h.get("old_target"), ensure_ascii=False),
                          json.dumps(h.get("new_target"), ensure_ascii=False), h.get("reason", "")))
    conn.commit()
    conn.close()
    return run_id


@router.post("/run")
def run_tests(body: RunIn, request: Request):
    """Chạy đúng các test case được chọn (API bằng HTTP, UI bằng Playwright) trên website đích.
    test_case_ids=None: toàn bộ (dành cho CLI). Danh sách rỗng là lỗi, không bao giờ hiểu thành "chạy tất cả".
    classify=true: AI phân loại lỗi luôn trong lượt này; giao diện dùng classify=false để hiện
    kết quả ngay rồi gọi /api/ai/classify sau."""
    from ai.quick_runner import run_api_test
    from ai.repro import curl, steps_text
    from ai.ui_runner import run_ui_tests
    url = body.url or _default_url()
    check_target(url, client_ip(request))
    if body.test_case_ids is not None and not body.test_case_ids:
        raise HTTPException(400, "Chưa chọn kịch bản nào để thực thi")
    base, api_paths, context = _target(url)

    cases = _load_cases(body.test_case_ids)
    if not cases:
        raise HTTPException(404, "Không có kịch bản nào để thực thi")
    if not _authorized(url, body.authorized):
        risky = [c.id for c in cases if c.category != "functional"
                 or any((s.method or "").upper() in ("PUT", "PATCH", "DELETE") for s in c.steps)]
        if risky:
            raise HTTPException(403, f"{len(risky)} kịch bản bảo mật, hiệu năng hoặc ghi/xoá dữ liệu cần xác nhận "
                                     "bạn có quyền kiểm thử hệ thống này.")
    requested = list(dict.fromkeys(body.test_case_ids)) if body.test_case_ids is not None else [c.id for c in cases]
    credentials = _credentials(body, url)
    local = is_local_target(url)
    before_each = _shop_reset_hook(base) if body.reset_shop else None

    out, failed = [], []
    with jobs.target_lock(url):
        ui_cases = [c for c in cases if c.type == "ui"]
        if ui_cases and before_each:
            before_each()
        ui_results = run_ui_tests(ui_cases, url, credentials=credentials) if ui_cases else {}
        for tc in cases:
            results = ui_results.get(tc.id, []) if tc.type == "ui" else run_api_test(
                tc, base, before_each=before_each, credentials=credentials, local=local)
            for res in results:
                item = {"test_case_id": tc.id, "title": tc.title, "type": tc.type, "category": tc.category, **res}
                if res["status"] == "failed":
                    item["repro"] = steps_text(tc)
                    item["curl"] = curl(item, base)
                    if body.classify:
                        failed.append((tc, item))
                out.append(item)

    # Chạy test tuần tự (shop được reset giữa các lượt) nhưng phân loại lỗi theo lô, song song
    for (_, item), verdict in zip(failed, _classify_parallel(failed, api_paths, context)):
        item["ai_analysis"] = verdict
    passed = sum(r["status"] == "passed" for r in out)
    flags = None
    if before_each:
        try:
            flags = _http.get(f"{base}/api/shop/bugs", timeout=5).json()
        except Exception:
            pass
    run_id = _save_run(url, cases, out, flags)
    found = {c.id for c in cases}
    return {"run_id": run_id, "target_url": base, "url": url, "requested_cases": len(requested), "cases_run": len(cases),
            "not_found": [i for i in requested if i not in found],
            "total": len(out), "passed": passed, "failed": len(out) - passed, "skipped_ui": [], "results": out}


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
    for f in fixes:
        conn.execute("UPDATE healing_patches SET status='applied' WHERE test_case_id=? AND step_idx=? AND status='pending'",
                     (tc.id, f.step_idx))
    conn.commit()
    conn.close()
    return {"ok": True, "test_case": tc.model_dump(exclude_none=True)}


class ClassifyIn(BaseModel):
    url: str | None = None
    items: list[dict]          # các phần tử "results" (không đạt) lấy từ /api/ai/run


@router.post("/classify")
def classify(body: ClassifyIn):
    """Phân loại một nhóm lỗi (giao diện gọi nhiều nhóm song song sau khi đã hiện kết quả)."""
    url = body.url or _default_url()
    _, api_paths, context = _target(url)
    by_id = {c.id: c for c in _load_cases(list({i.get("test_case_id") for i in body.items}))}
    pairs = [(by_id.get(i.get("test_case_id")) or {"id": i.get("test_case_id"), "type": "api", "steps": []}, i)
             for i in body.items]
    verdicts = _classify_parallel(pairs, api_paths, context)
    conn = get_conn()
    for item, verdict in zip(body.items, verdicts):
        if item.get("result_id"):
            conn.execute("UPDATE results SET ai_analysis_json=? WHERE id=?",
                         (json.dumps(verdict, ensure_ascii=False), item["result_id"]))
    conn.commit()
    conn.close()
    return verdicts


class AutopilotIn(BaseModel):
    url: str | None = None
    save: bool = True
    include_api: bool = True
    username: str | None = None      # tài khoản thử nghiệm (tuỳ chọn) cho website cần đăng nhập
    password: str | None = None
    use_demo_account: bool = False   # Demo Shop: dùng tài khoản demo trong .env (mật khẩu không qua trình duyệt)
    paths: list[str] = []            # đường đi người dùng cung cấp: trang cần duyệt (vd. /cart)
    flow: str = ""                   # đường đi người dùng cung cấp: luồng nghiệp vụ cần kiểm thử
    verify: bool = True              # chạy thử kịch bản ngay sau khi sinh
    authorized: bool = False         # đã xác nhận có quyền kiểm thử hệ thống đích


@router.post("/autopilot")
def autopilot(body: AutopilotIn, request: Request):
    """Dán URL → Explorer duyệt website + OpenAPI, sinh kịch bản; Reviewer chấm điểm; Verifier chạy thử."""
    return _autopilot(body, client_ip(request))


@router.post("/jobs/autopilot")
def autopilot_job(body: AutopilotIn, request: Request):
    client = client_ip(request)
    check_target(body.url or _default_url().rstrip("/") + "/shop", client)
    return {"job_id": jobs.start(lambda on_step: _autopilot(body, client, on_step))}


def _autopilot(body: AutopilotIn, client: str | None, on_step=None) -> dict:
    import time
    from ai.agents import Trace, review_and_fix, verify_and_repair
    from ai.autopilot import fetch_samples, find_openapi
    from ai.skills import context as skill_context
    from backend.quality_routes import save_reviews
    url = body.url or _default_url().rstrip("/") + "/shop"
    check_target(url, client)
    trace, t0 = Trace(on_step), time.perf_counter()
    trace.start("explorer", "Mở trình duyệt, duyệt các trang…")
    used: list[str] = []
    try:
        if ai_client.USE_MOCK:
            r = ai_client.autopilot(url)
        else:
            from ai.autopilot import autopilot as real
            login = {"username": body.username, "password": body.password} if body.username and body.password else None
            if body.use_demo_account and os.getenv("SHOP_DEMO_EMAIL") and os.getenv("SHOP_DEMO_PASSWORD"):
                login = {"username": os.getenv("SHOP_DEMO_EMAIL"), "password": os.getenv("SHOP_DEMO_PASSWORD")}
            if login:
                vault.remember(url, login["username"], login["password"])
            guidance, used, _ = skill_context("explorer", body.flow + " giao diện checkout đăng nhập", urlparse(url).netloc)
            r = real(url, include_api=body.include_api, login=login, paths=body.paths, flow=body.flow, guidance=guidance)
    except Exception as e:
        raise HTTPException(502, f"Autopilot lỗi: {e}")
    trace.add("explorer", "ok", int((time.perf_counter() - t0) * 1000),
              f"Duyệt {len(r['pages'])} trang, đề xuất {len(r['test_cases'])} kịch bản", skills=used)
    spec = find_openapi(url)
    _save_snapshot(url, spec)
    llm = _llm_or_none()
    reviewed = review_and_fix(r["test_cases"], body.flow, spec, llm, trace, urlparse(url).netloc, ai_review_enabled=False)
    r["test_cases"] = reviewed["cases"]
    stats = {"pages": len(r["pages"]), "produced": len(r["test_cases"])}
    if body.verify and llm is not None and r["test_cases"]:
        if _authorized(url, body.authorized):
            samples = fetch_samples(url, spec) if spec else ""
            verifier = _make_verifier(url, spec, samples, body.flow, vault.get(url) or _credentials(body, url), llm)
            try:
                vs = verify_and_repair(r["test_cases"], reviewed["reviews"], body.flow, spec, llm, trace, verifier)
                stats.update(verify_first=vs["first"], verify_final=vs["final"], repaired=vs["repaired"])
            except Exception as e:    # chạy thử lỗi không làm mất kịch bản đã sinh
                trace.add("verifier", "error", 0, f"Không chạy thử được: {str(e)[:160]}")
        else:
            trace.add("verifier", "skip", 0, "Bỏ qua chạy thử: chưa xác nhận quyền kiểm thử hệ thống này")
    req_id = None
    if body.save and r["test_cases"]:
        req_id = _save_cases(r["test_cases"], f"[Autopilot] {url}")
        save_reviews(reviewed["reviews"])
    _save_agent_run("autopilot", url, req_id, trace.steps, stats)
    return {**r, "test_cases": [t.model_dump(exclude_none=True) for t in r["test_cases"]], "reviews": reviewed["reviews"],
            "trace": trace.steps, "requirement_id": req_id}


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
def heal(body: HealIn, request: Request):
    """Self-healing: đề xuất locator mới cho bước UI bị hỏng."""
    dom = body.dom
    if not dom:
        from playwright.sync_api import sync_playwright
        url = body.url or _default_url().rstrip("/") + "/shop"
        check_target(url, client_ip(request))
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

# SPDX-License-Identifier: Apache-2.0
"""Test lớp nền tảng: thực thi đúng kịch bản đã chọn, bảo mật, agent duyệt, skill, bảo trì.
Dùng DB tạm, không gọi AI thật, không đụng dữ liệu của người dùng."""

import json
import os
import sqlite3

import pytest

os.environ["USE_MOCK"] = "1"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from backend import db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "tp.db")
    monkeypatch.setenv("TESTPILOT_TOKEN", "")
    from fastapi.testclient import TestClient
    from backend.main import app
    from backend.security import limiter
    limiter.hits.clear()
    with TestClient(app) as c:
        yield c


def _case(i, **kw):
    from backend.models import TestCase
    base = dict(id=f"TC-{i}", title=f"Kịch bản số {i}", type="api",
                steps=[{"method": "GET", "path": "/api/shop/products", "expect": {"status": 200}}])
    return TestCase(**{**base, **kw})


def _seed(cases, url="http://testserver/shop"):
    from backend.ai_routes import _save_cases
    return _save_cases(cases, f"[{url}] yêu cầu")


def _fake_runner(monkeypatch):
    """Ghi lại đúng những kịch bản runner nhận được."""
    ran = []

    def fake(tc, base, **kw):
        ran.append(tc.id)
        return [{"data_set": d.name, "expected": "accept", "status": "passed", "error_msg": "", "duration_ms": 1}
                for d in (tc.data_sets or [type("D", (), {"name": "-"})])]

    monkeypatch.setattr("ai.quick_runner.run_api_test", fake)
    monkeypatch.setattr("backend.ai_routes._target", lambda url: ("http://testserver", None, ""))
    monkeypatch.setattr("backend.ai_routes._shop_reset_hook", lambda base: None)
    return ran


# ---------- Lỗi "chọn 4 mà chạy 24" ----------
def test_run_executes_exactly_the_selected_cases(client, monkeypatch):
    _seed([_case(i) for i in range(24)])
    ran = _fake_runner(monkeypatch)
    picked = ["TC-3", "TC-7", "TC-1", "TC-20"]
    r = client.post("/api/ai/run", json={"test_case_ids": picked, "classify": False}).json()
    assert ran == picked                      # đúng 4, đúng thứ tự
    assert r["cases_run"] == 4 and r["requested_cases"] == 4 and r["total"] == 4


def test_empty_selection_never_means_run_all(client, monkeypatch):
    _seed([_case(i) for i in range(24)])
    ran = _fake_runner(monkeypatch)
    r = client.post("/api/ai/run", json={"test_case_ids": [], "classify": False})
    assert r.status_code == 400 and ran == []


def test_report_separates_cases_from_data_set_runs(client, monkeypatch):
    sets = [{"name": f"s{k}", "values": {}} for k in range(6)]
    _seed([_case(i, data_sets=sets) for i in range(4)])
    _fake_runner(monkeypatch)
    r = client.post("/api/ai/run", json={"test_case_ids": [f"TC-{i}" for i in range(4)], "classify": False}).json()
    assert r["cases_run"] == 4 and r["total"] == 24


def test_unknown_ids_are_reported_not_replaced(client, monkeypatch):
    _seed([_case(1), _case(2)])
    ran = _fake_runner(monkeypatch)
    r = client.post("/api/ai/run", json={"test_case_ids": ["TC-1", "TC-404"], "classify": False}).json()
    assert ran == ["TC-1"] and r["not_found"] == ["TC-404"]


def test_own_platform_apis_are_never_tested():
    from ai.test_generator import is_excluded
    for p in ("/api/quality/metrics", "/api/knowledge/skills", "/api/maintenance/drift", "/api/ai/run", "/api/shop/bugs"):
        assert is_excluded(p)
    assert not is_excluded("/api/shop/checkout")


def test_regenerating_same_requirement_does_not_overwrite_old_batch():
    from ai.test_generator import _prefix_for
    assert _prefix_for("cùng một yêu cầu") != _prefix_for("cùng một yêu cầu")


def test_frontend_runs_only_visible_selection():
    """Giao diện không còn đường "không tick thì chạy tất cả", và chạy theo selected()."""
    from pathlib import Path
    html = Path("frontend/ai.html").read_text(encoding="utf-8")
    assert "runnable()" not in html
    assert ':disabled="busy || !selected().length"' in html
    assert "this.picked = r.ids" not in html


# ---------- Mật khẩu ----------
def test_scrub_removes_real_password_from_autopilot_cases(tmp_path, monkeypatch):
    from backend import db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "s.db")
    monkeypatch.setenv("SHOP_DEMO_PASSWORD", "DemoSecret#1")
    db.init_db()
    conn = db.get_conn()
    conn.execute("INSERT INTO requirements(text) VALUES ('[Autopilot] https://x.example')")
    data = {"id": "A", "title": "t", "type": "ui", "steps": [{"action": "goto", "url": "/"}], "data_sets": [
        {"name": "real", "values": {"username": "sv01", "password": "Th1sIsReal!"}},
        {"name": "neg", "values": {"username": "sv01", "password": "wrongpass"}}]}
    conn.execute("INSERT INTO test_cases(id, requirement_id, json) VALUES ('A', 'REQ-1', ?)", (json.dumps(data),))
    conn.commit()
    conn.close()
    db.init_db()
    raw = (tmp_path / "s.db").read_bytes()
    assert b"Th1sIsReal!" not in raw and b"sv01" not in raw     # VACUUM xoá cả trang trống
    conn = db.get_conn()
    d = json.loads(conn.execute("SELECT json FROM test_cases").fetchone()["json"])
    conn.close()
    assert d["data_sets"][0]["values"] == {"username": "__USERNAME__", "password": "__PASSWORD__"}
    assert d["data_sets"][1]["values"]["password"] == "wrongpass"


def test_markers_need_credentials_at_run_time():
    from ai.quick_runner import MissingCredentials, run_variables
    from backend.models import DataSet
    ds = DataSet(name="x", values={"u": "__USERNAME__", "p": "__PASSWORD__"})
    with pytest.raises(MissingCredentials):
        run_variables(ds)
    v = run_variables(ds, {"username": "a", "password": "b"})
    assert v["u"] == "a" and v["p"] == "b"


def test_redact_masks_nested_secrets():
    from ai.quick_runner import redact
    assert redact({"email": "a@b.c", "password": "x", "n": [{"api_token": "y"}]}) == \
        {"email": "a@b.c", "password": "••••••", "n": [{"api_token": "••••••"}]}


# ---------- Bảo vệ ứng dụng ----------
@pytest.mark.parametrize("url,code", [("http://169.254.169.254/latest/meta-data", 403), ("http://metadata.google.internal/", 403),
                                      ("file:///etc/passwd", 400), ("ftp://x.example/", 400), ("http://user:pw@example.com/", 400)])
def test_inspect_blocks_ssrf(client, url, code):
    assert client.get("/api/ai/inspect", params={"url": url}).status_code == code


def test_private_target_blocked_for_remote_client():
    from fastapi import HTTPException
    from backend.security import check_target
    check_target("http://127.0.0.1:9000/", "127.0.0.1")     # người dùng trên chính máy chủ: được
    with pytest.raises(HTTPException):
        check_target("http://127.0.0.1:9000/", "203.0.113.9")
    with pytest.raises(HTTPException):
        check_target("http://10.0.0.5/", "203.0.113.9")


def test_security_headers_present(client):
    h = client.get("/ai.html").headers
    assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "SAMEORIGIN"
    assert "frame-ancestors" in h["content-security-policy"]


def test_token_required_when_configured(client, monkeypatch):
    monkeypatch.setenv("TESTPILOT_TOKEN", "bi-mat")
    assert client.get("/api/test-cases").status_code == 401
    assert client.get("/api/test-cases", headers={"X-TestPilot-Token": "bi-mat"}).status_code == 200
    assert client.get("/api/shop/products").status_code == 200   # shop là hệ thống đích, không thuộc phạm vi token


def test_rate_limit(client, monkeypatch):
    monkeypatch.setenv("AI_RATE_LIMIT", "2")
    codes = [client.post("/api/quality/review", json={"ids": ["x"]}).status_code for _ in range(3)]
    assert codes[-1] == 429


def test_security_cases_need_authorization_on_external_target(client, monkeypatch):
    monkeypatch.setattr("backend.ai_routes.is_local_target", lambda u: False)
    r = client.post("/api/ai/generate", json={"text": "x", "url": "https://example.com", "categories": ["security"]})
    assert r.status_code == 403


def test_excel_formula_injection_is_neutralised():
    from backend.export import _safe
    assert _safe("=HYPERLINK(\"http://x\")").startswith("'=") and _safe("-1+1").startswith("'-") and _safe("bình thường") == "bình thường"


def test_ui_runner_refuses_goto_outside_target():
    from ai.ui_runner import do_step
    from backend.models import Step
    with pytest.raises(ValueError):
        do_step(None, Step(action="goto", url="https://evil.example/"), "http://127.0.0.1:8000")


# ---------- Agent duyệt ----------
SPEC = {"paths": {"/api/orders": {"post": {"requestBody": {"content": {"application/json": {"schema": {"required": ["email", "items"]}}}}}},
                  "/api/orders/{id}": {"get": {}}}}


def test_review_flags_real_problems():
    from ai.review import lint, score_of
    from backend.models import TestCase
    bad = TestCase(id="A", title="Đặt hàng thành công", type="api", steps=[
        {"method": "POST", "path": "/api/orders", "body": {"email": "a@b.c"}, "expect": {"status": 201}},
        {"method": "GET", "path": "/api/khong-co", "expect": {"status": 200}},
        {"method": "DELETE", "path": "/api/orders/1"}])
    codes = {i["code"] for i in lint(bad, SPEC)}
    assert {"R13", "R11", "R12", "R10"} <= codes
    assert score_of(lint(bad, SPEC))[1] == "reject"


def test_review_approves_good_case():
    from ai.review import lint, score_of
    from backend.models import TestCase
    good = TestCase(id="B", title="Đặt hàng rồi tra cứu lại đơn", type="api", steps=[
        {"method": "POST", "path": "/api/orders", "body": {"email": "a@b.c", "items": [1]}, "expect": {"status": 201}, "save": {"id": "id"}},
        {"method": "GET", "path": "/api/orders/{{id}}", "expect": {"status": 200, "json_contains": {"email": "a@b.c"}}}])
    assert score_of(lint(good, SPEC)) == (100, "approve")


def test_review_ui_rules():
    from ai.review import lint
    from backend.models import TestCase
    weak = TestCase(id="C", title="Bấm nút mua hàng", type="ui", steps=[
        {"action": "click", "target": {"css": "div > ul > li:nth-child(3) > a"}}])
    codes = {i["code"] for i in lint(weak)}
    assert {"R20", "R21", "R23", "R24"} <= codes


def test_duplicate_detection():
    from ai.review import lint
    a, b = _case(1), _case(2)
    assert any(i["code"] == "R04" for i in lint(a, None, [a, b]))


# ---------- Pipeline agent ----------
class Fake:
    name, model, last_used = "fake", "fake", None

    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    def complete_json(self, system, user):
        self.calls.append(user)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


GOOD = {"title": "Xem danh sách sản phẩm đầy đủ", "type": "api",
        "steps": [{"method": "GET", "path": "/api/shop/products", "expect": {"status": 200, "json_contains": [{"id": "x"}]}}]}
BAD = {"title": "Đăng ký tài khoản mới", "type": "api",
       "steps": [{"method": "POST", "path": "/api/shop/register", "body": {"email": "co-dinh@example.com"}}]}


def test_pipeline_fixer_keeps_only_improvements(tmp_path, monkeypatch):
    from ai import agents
    from backend import db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "p.db")
    db.init_db()
    fixed = {**BAD, "id": "@@", "steps": [{"method": "POST", "path": "/api/shop/register",
                                           "body": {"email": "{{$email}}"}, "expect": {"status": 201}}]}
    fake = Fake({"test_cases": [GOOD, BAD]}, {"criteria": [{"text": "xem sản phẩm", "covered_by": []}], "reviews": []}, None)

    def fix(system, user):
        import re
        ids = re.findall(r'"id": "(TC-[^"]+)"', user)
        return {"test_cases": [{**fixed, "id": ids[0]}]}
    res_iter = iter([fake.responses[0], fake.responses[1]])
    fake.complete_json = lambda s, u: next(res_iter, None) or fix(s, u)
    r = agents.generate_pipeline("Xem sản phẩm và đăng ký", "http://x/shop", provider=fake, lead=False)
    agents_seen = [t["agent"] for t in r["trace"]]
    assert agents_seen == ["context", "writer", "reviewer", "fixer"]
    fixed_review = [v for v in r["reviews"].values() if v.get("source") == "fixer"]
    assert fixed_review and fixed_review[0]["score"] > fixed_review[0]["fixed_from"]
    assert any("{{$email}}" in json.dumps(c.steps[0].body or {}) for c in r["cases"])


def test_pipeline_survives_llm_failure_and_keeps_security_cases(tmp_path, monkeypatch):
    from ai import agents
    from backend import db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "p2.db")
    db.init_db()
    spec = {"paths": {"/api/shop/auth/login": {"post": {"requestBody": {"content": {"application/json": {"schema": {
        "type": "object", "required": ["email", "password"],
        "properties": {"email": {"type": "string"}, "password": {"type": "string"}}}}}}}},
        "/api/shop/products": {"get": {}}}}

    class Down:
        name, model, last_used = "down", "m", None

        def complete_json(self, s, u):
            raise RuntimeError("hết hạn mức")
    r = agents.generate_pipeline("Đăng nhập", "http://x/shop", categories=["functional", "security", "performance"], spec=spec, provider=Down())
    cats = {c.category for c in r["cases"]}
    assert cats == {"security", "performance"} and r["warnings"]
    assert any(t["agent"] == "writer" and t["status"] == "error" for t in r["trace"])


def test_security_builder_finds_idor_flow():
    from ai.security_tests import build_security_cases
    from backend.models import TestCase
    from ShopDemo import router  # noqa: F401
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)
    cases = build_security_cases(app.openapi(), "http://x/shop", {"id": "iphone-15"})
    titles = " | ".join(c.title for c in cases)
    assert "từ chối người chưa đăng nhập" in titles and "Đăng nhập sai liên tiếp" in titles and "Cookie phiên" in titles
    idor = next(c for c in cases if "IDOR" in (c.technique or ""))
    assert [s.method for s in idor.steps] == ["POST", "POST", "POST", "GET"]
    assert all(isinstance(c, TestCase) and c.category == "security" for c in cases)
    # không dò API quản trị của shop
    assert not any("/bugs" in (s.path or "") or "/reset" in (s.path or "") for c in cases for s in c.steps)


# ---------- Runner mở rộng ----------
def test_check_expect_variants():
    import httpx
    from ai.quick_runner import check_expect
    r = httpx.Response(200, headers={"Set-Cookie": "a=b; HttpOnly", "content-type": "text/html"}, text="<script>x</script> traceback")
    assert "status in" in check_expect({"status_in": [401, 403]}, r, None, 1)
    assert "header" in check_expect({"headers": ["X-Frame-Options"]}, r, None, 1)
    assert "SameSite".lower() in check_expect({"cookie_flags": ["httponly", "samesite"]}, r, None, 1).lower()
    assert "traceback" in check_expect({"not_contains": ["traceback"]}, r, None, 1)
    assert "XSS" in check_expect({"not_reflected_html": "<script>x</script>"}, r, None, 1)
    assert "within" in check_expect({"max_ms": 10}, r, None, 50)
    assert check_expect({"status_lt": 500}, r, None, 1) is None


def test_perf_caps_on_remote_target(monkeypatch):
    import ai.quick_runner as q
    from backend.models import Step
    seen = []

    class R:
        status_code = 200

    monkeypatch.setattr(q._http, "request", lambda *a, **k: (seen.append(1), R())[1])
    m, err = q.run_perf(Step(method="GET", path="/x", perf={"requests": 5000, "concurrency": 500}), "https://x.example", "/x", None, local=False)
    assert m["requests"] == q.REMOTE_REQUESTS and m["concurrency"] == q.REMOTE_CONCURRENCY and len(seen) == q.REMOTE_REQUESTS and err is None


def test_login_limit_check_fails_when_never_blocked(monkeypatch):
    import ai.quick_runner as q
    from backend.models import Step

    class R:
        status_code = 401

    monkeypatch.setattr(q._http, "request", lambda *a, **k: R())
    _, err = q.run_perf(Step(method="POST", path="/l", perf={"requests": 3, "concurrency": 1, "min_blocked": 1}), "http://x", "/l", {}, local=True)
    assert "không bị giới hạn" in err


# ---------- Skill và bài học ----------
def test_skill_selection_by_agent_and_trigger(tmp_path, monkeypatch):
    from ai import skills
    from backend import db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "k.db")
    db.init_db()
    ids = {s.id for s in skills.select("writer", "Đăng nhập rồi đặt hàng")}
    assert {"api-contract", "auth-session", "ecommerce-checkout"} <= ids and "security-owasp" not in ids
    assert "auth-session" not in {s.id for s in skills.select("writer", "xem thời tiết")}
    assert "security-owasp" in {s.id for s in skills.select("security", "x")}


def test_only_approved_lessons_reach_the_prompt(client):
    r = client.post("/api/knowledge/lessons", json={"text": "POST register trả về 201"})
    lid = r.json()["id"]
    from ai import skills
    assert "POST register" in skills.context("writer", "x")[0]
    client.put(f"/api/knowledge/lessons/{lid}", json={"status": "disabled"})
    assert "POST register" not in skills.context("writer", "x")[0]


def test_rejecting_with_reason_creates_pending_lesson_only(client):
    _seed([_case(1)])
    client.post("/api/quality/review/TC-1/decision", json={"decision": "rejected", "reason": "Sai mã lỗi, phải là 422"})
    lessons = client.get("/api/knowledge/lessons").json()
    assert lessons[0]["status"] == "pending"
    from ai import skills
    assert "Sai mã lỗi" not in skills.context("writer", "x")[0]


def test_custom_skill_lifecycle_and_toggle(client):
    sid = client.post("/api/knowledge/skills", json={"name": "Đăng ký học phần", "agents": ["writer"], "body": "Always check prerequisites."}).json()["id"]
    from ai import skills
    assert "prerequisites" in skills.context("writer", "x")[0]
    client.put(f"/api/knowledge/skills/{sid}", json={"enabled": False})
    assert "prerequisites" not in skills.context("writer", "x")[0]
    client.put("/api/knowledge/skills/api-contract", json={"enabled": False})
    assert "api-contract" not in {s.id for s in skills.select("writer", "x")}
    assert client.delete(f"/api/knowledge/skills/{sid}").status_code == 200


def test_dataset_contains_only_approved_and_masks_secrets(client):
    _seed([_case(1, data_sets=[{"name": "d", "values": {"password": "lo-mat"}}]), _case(2)])
    client.post("/api/quality/review/TC-1/decision", json={"decision": "approved"})
    client.post("/api/quality/review/TC-2/decision", json={"decision": "rejected"})
    body = client.get("/api/knowledge/dataset.jsonl").text
    assert "TC-1" in body and "TC-2" not in body and "lo-mat" not in body
    assert json.loads(body.splitlines()[0])["messages"][1]["content"] == "yêu cầu"


# ---------- Bảo trì ----------
def test_impact_and_apply_versions_requirement(client, monkeypatch):
    req_id = _seed([_case(1), _case(2)])
    monkeypatch.setattr("ai.autopilot.find_openapi", lambda u: None)
    monkeypatch.setattr("backend.ai_client.find_affected_tests", lambda old, new, tcs: {
        "affected": [{"id": "TC-1", "action": "obsolete", "reason": "bỏ"}], "uncovered": []})
    r = client.post("/api/maintenance/impact", json={"requirement_id": req_id, "new_text": "yêu cầu mới"}).json()
    assert r["unchanged"] == 1 and r["affected"][0]["title"]
    a = client.post("/api/maintenance/apply", json={"requirement_id": req_id, "new_text": "yêu cầu mới",
                                                    "affected": r["affected"], "uncovered": []}).json()
    assert a["obsolete"] == ["TC-1"] and a["requirement_id"] != req_id
    active = {c["id"]: c for c in client.get("/api/test-cases").json()}
    assert "TC-1" not in active and active["TC-2"]["requirement_id"] == f"REQ-{a['requirement_id']}"
    reqs = client.get("/api/maintenance/requirements").json()
    assert reqs[0]["parent_id"] == req_id


def test_drift_detects_removed_endpoint(client, monkeypatch):
    from backend.ai_routes import _save_snapshot
    url = "http://testserver/shop"
    _seed([_case(1, steps=[{"method": "GET", "path": "/api/old", "expect": {"status": 200}}])])
    old = {"paths": {"/api/old": {"get": {}}, "/api/keep": {"get": {}}}}
    _save_snapshot(url, old)
    monkeypatch.setattr("ai.autopilot.find_openapi", lambda u: {"paths": {"/api/keep": {"get": {}}, "/api/new": {"post": {}}}})
    r = client.get("/api/maintenance/drift", params={"url": url}).json()
    assert r["removed"] == ["GET /api/old"] and r["added"] == ["POST /api/new"]
    assert r["broken_cases"][0]["id"] == "TC-1"


def test_healing_patch_needs_human_approval(client):
    from backend.db import get_conn
    _seed([_case(1, type="ui", steps=[{"action": "goto", "url": "/"}, {"action": "click", "target": {"testid": "cu"}}])])
    conn = get_conn()
    pid = conn.execute("INSERT INTO healing_patches(test_case_id, step_idx, old_target, new_target, reason) VALUES ('TC-1', 1, ?, ?, 'đổi tên')",
                       (json.dumps({"testid": "cu"}), json.dumps({"testid": "moi"}))).lastrowid
    conn.commit()
    conn.close()
    assert client.get("/api/test-cases").json()[0]["steps"][1]["target"]["testid"] == "cu"
    client.post(f"/api/maintenance/healings/{pid}", json={"decision": "applied"})
    assert client.get("/api/test-cases").json()[0]["steps"][1]["target"]["testid"] == "moi"
    assert client.get("/api/maintenance/healings").json()[0]["status"] == "applied"


def test_locator_scoring():
    from ai.locators import inspect_elements, summarize
    html = '''<button data-testid="buy">Mua</button><button>Mua</button><input id="ember123" placeholder="Tên"><a href="/x">Về</a>'''
    counts = {'[data-testid="buy"]': 1, 'role=button[name="Mua"]': 2}
    rows = inspect_elements(html, lambda sel: counts.get(sel, 1))
    assert rows[0]["best"]["kind"] == "testid" and rows[0]["best"]["score"] == 100
    second = rows[1]["best"]
    assert second["score"] < 75         # role + tên khớp 2 phần tử nên bị trừ điểm
    assert summarize(rows)["elements"] == 4


def test_repro_and_curl_hide_passwords():
    from ai.repro import curl, steps_text
    from backend.models import TestCase
    tc = TestCase(id="X", title="t", type="api", steps=[{"method": "POST", "path": "/l", "body": {"password": "p"}, "expect": {"status": 200}}])
    assert "••••••" in steps_text(tc)[0] and "HTTP 200" in steps_text(tc)[0]
    assert "curl -i -X POST" in curl({"request": {"method": "POST", "path": "/l", "body": {"a": 1}}}, "http://x")


def test_sample_pack_is_not_counted_as_ai_output(client, monkeypatch):
    monkeypatch.setattr("ai.autopilot.find_openapi", lambda u: None)
    from backend.quality_routes import save_reviews
    _seed([_case("DEMO-01"), _case(1)], url="http://127.0.0.1:8000/shop")
    save_reviews({"TC-DEMO-01": {"score": 100, "verdict": "approve", "issues": []},
                  "TC-1": {"score": 40, "verdict": "reject", "issues": []}})
    m = client.get("/api/quality/metrics", params={"url": "http://127.0.0.1:8000/shop"}).json()
    assert m["review"]["reviewed"] == 1 and m["review"]["approve_pct"] == 0


def test_metrics_report_none_without_data(client, monkeypatch):
    monkeypatch.setattr("ai.autopilot.find_openapi", lambda u: None)
    m = client.get("/api/quality/metrics").json()
    assert m["generation"]["schema_valid_pct"] is None and m["execution"]["usable_pct"] is None and m["benchmark"] is None


# ---------- Lead, Verifier, Fixer an toàn ----------
def _api(cid, status=201, extra=None, path="/api/shop/checkout"):
    from backend.models import TestCase
    return TestCase(id=cid, title="Đặt hàng hợp lệ trả về 201", type="api",
                    steps=[{"method": "POST", "path": path, "expect": {"status": status, **(extra or {})}}])


def test_fix_rejected_when_it_removes_checks():
    from ai.agents import weakened
    old = _api("A", extra={"json_contains": {"total": 1, "email": "x"}})
    new = _api("A", extra={"json_contains": {"total": 1}})
    assert "giảm" in weakened(old, new, "")


def test_fix_rejected_when_it_changes_status_stated_in_requirement():
    from ai.agents import weakened
    req = "Đặt vượt số lượng tồn kho trả về 409."
    assert "409" in weakened(_api("A", 409), _api("A", 422), req)
    assert weakened(_api("A", 200), _api("A", 201), "Đặt hàng thành công") is None     # yêu cầu không nêu mã: được đổi


class _Scripted:
    """LLM giả: trả lần lượt các câu trả lời."""
    name, model, last_used = "fake", "fake", None

    def __init__(self, *answers):
        self.answers, self.calls = list(answers), 0

    def complete_json(self, system, user):
        self.calls += 1
        return self.answers.pop(0)


def _reviews_for(cases):
    from ai.review import review_cases
    return review_cases(cases)


def test_verifier_flow_repairs_only_test_bugs_and_keeps_app_bugs():
    from ai.agents import Trace, verify_and_repair
    good, broken, buggy = _api("TC-1"), _api("TC-2", 200), _api("TC-3")
    cases = [good, broken, buggy]
    fixed = {"id": "TC-2", "title": "Đặt hàng hợp lệ trả về 201", "type": "api",
             "steps": [{"method": "POST", "path": "/api/shop/checkout", "expect": {"status": 201}}]}
    llm = _Scripted({"test_cases": [fixed]})
    calls = []

    def verifier(batch):
        calls.append([c.id for c in batch])
        out = {}
        for c in batch:
            if c.id == "TC-3":
                out[c.id] = {"status": "app_bug", "detail": "tổng tiền sai"}
            elif c.id == "TC-2" and c.steps[0].expect["status"] == 200:
                out[c.id] = {"status": "test_broken", "detail": "API trả 201", "evidence": {"actual_status": 201}}
            else:
                out[c.id] = {"status": "passed"}
        return out

    reviews = _reviews_for(cases)
    r = verify_and_repair(cases, reviews, "Đặt hàng thành công", None, llm, Trace(), verifier)
    assert calls == [["TC-1", "TC-2", "TC-3"], ["TC-2"]]      # chỉ chạy lại kịch bản đã sửa
    assert r["first"]["test_broken"] == 1 and r["final"]["test_broken"] == 0 and r["repaired"] == 1
    assert cases[2].steps[0].expect["status"] == 201 and reviews["TC-3"]["verification"] == "app_bug"
    assert llm.calls == 1                                       # không gọi Fixer cho lỗi ứng dụng
    assert any(i["code"] == "V02" for i in reviews["TC-2"]["issues"])   # đổi kỳ vọng: cần người xác nhận


def test_repair_that_still_fails_keeps_original_and_marks_high_issue():
    from ai.agents import Trace, verify_and_repair
    broken = _api("TC-2", 200)
    cases = [broken]
    llm = _Scripted({"test_cases": [{"id": "TC-2", "title": "Đặt hàng hợp lệ trả về 201", "type": "api",
                                     "steps": [{"method": "POST", "path": "/api/shop/checkout", "expect": {"status": 202}}]}]})
    verifier = lambda batch: {c.id: {"status": "test_broken", "detail": "vẫn lỗi", "evidence": {}} for c in batch}
    reviews = _reviews_for(cases)
    r = verify_and_repair(cases, reviews, "Đặt hàng thành công", None, llm, Trace(), verifier, max_rounds=1)
    assert cases[0].steps[0].expect["status"] == 200 and r["repaired"] == 0
    assert reviews["TC-2"]["verdict"] != "approve" and any(i["code"] == "V01" for i in reviews["TC-2"]["issues"])


def test_security_probe_is_never_rewritten():
    from ai.agents import Trace, verify_and_repair
    probe = _api("TC-S1", 401)
    llm = _Scripted()
    reviews = _reviews_for([probe])
    verify_and_repair([probe], reviews, "x", None, llm, Trace(),
                      lambda b: {c.id: {"status": "test_broken", "detail": "", "evidence": {}} for c in b}, {"TC-S1"})
    assert llm.calls == 0


def test_verify_detects_flaky_and_skips_llm_when_all_pass(monkeypatch):
    import ai.verifier as v
    runs = {"n": 0}

    def fake_run(tc, base, **kw):
        runs["n"] += 1
        return [{"status": "failed" if runs["n"] == 1 else "passed", "error_msg": "timeout"}]
    monkeypatch.setattr(v, "run_api_test", fake_run)
    out = v.verify([_api("TC-1")], "http://x", "http://x")
    assert out["TC-1"]["status"] == "flaky"


def test_pipeline_lead_plans_and_fills_uncovered_criteria(tmp_path, monkeypatch):
    from ai import agents
    from backend import db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "l.db")
    db.init_db()
    case = {"title": "Xem danh sách sản phẩm", "type": "api",
            "steps": [{"method": "GET", "path": "/p", "expect": {"status": 200, "json_contains": [{"id": "x"}]}}]}
    other = {**case, "title": "Tìm sản phẩm theo tên hãng"}
    llm = _Scripted({"summary": "Kiểm tra sản phẩm", "criteria": ["Xem", "Tìm"], "focus": [], "count": 4, "suggest": ["security"]},
                    {"test_cases": [case]},
                    {"criteria": [{"text": "Xem", "covered_by": ["__any__"]}, {"text": "Tìm", "covered_by": []}], "reviews": []},
                    {"test_cases": [other]})
    r = agents.generate_pipeline("- Xem\n- Tìm", "http://x/shop", provider=llm, auto_fix=False)
    assert [t["agent"] for t in r["trace"]][:2] == ["context", "lead"]
    assert len(r["cases"]) == 2 and r["plan"]["suggest"] == ["security"]
    assert {c.category for c in r["cases"]} == {"functional"}      # Lead chỉ gợi ý, không tự bật bảo mật
    assert all(c["covered_by"] for c in r["criteria"])


def test_lead_cannot_exceed_case_cap():
    from ai.agents import make_plan
    p = make_plan("x", ["functional"], None, None, _Scripted({"criteria": ["a"], "count": 500}))
    assert p["count"] == 12


def test_parse_p95_from_requirement():
    from ai.agents import parse_p95
    assert parse_p95("phản hồi dưới 500ms") == 500 and parse_p95("trong 2 giây") == 2000 and parse_p95("không nói gì") is None


def test_job_reports_progress_and_errors():
    import time as _t
    from fastapi import HTTPException
    from backend import jobs

    def ok(on_step):
        on_step([{"agent": "lead", "status": "running"}])
        return {"done": 1}

    def bad(on_step):
        raise HTTPException(403, "không có quyền")
    a, b = jobs.start(ok), jobs.start(bad)
    for _ in range(50):
        if jobs.get(a)["status"] != "running" and jobs.get(b)["status"] != "running":
            break
        _t.sleep(0.02)
    assert jobs.get(a)["result"] == {"done": 1} and jobs.get(a)["trace"][0]["agent"] == "lead"
    assert jobs.get(b)["error"] == "không có quyền"


def test_every_skill_is_reachable_by_an_llm_agent():
    from ai.skills import builtin_skills
    llm_agents = {"writer", "explorer", "reviewer", "security", "triage"}
    assert all(set(s.agents) & llm_agents for s in builtin_skills())


def test_assert_text_ignores_line_breaks_between_blocks():
    from ai.ui_runner import _assert_text

    class Loc:
        def inner_text(self, timeout=None):
            return "1\n  Giỏ hàng"
    assert "thấy" in _assert_text(Loc(), "1 Giỏ hàng", 100)
    with pytest.raises(AssertionError):
        _assert_text(Loc(), "2 Giỏ hàng", 100)


def test_dig_accepts_bracket_index():
    from ai.quick_runner import dig
    data = {"items": [{"id": 7}]}
    assert dig(data, "items[0].id") == 7 and dig(data, "items.0.id") == 7 and dig([{"a": 1}], "[0].a") == 1


def test_generated_performance_cases_are_not_rewritten_by_fixer(tmp_path, monkeypatch):
    from ai import agents
    from backend import db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "f.db")
    db.init_db()
    llm = _Scripted({"criteria": [], "reviews": []})
    monkeypatch.setattr("ai.review.score_of", lambda issues: (40, "reject"))     # mọi kịch bản đều bị chê
    r = agents.generate_pipeline("đo tốc độ", "http://x/shop", categories=["performance"], provider=llm, lead=False)
    assert llm.calls == 0 and all(c.category == "performance" for c in r["cases"])    # không gọi Reviewer AI, không gọi Fixer


# ---------- Giảm phụ thuộc vào LLM ----------
def _shop_spec():
    from fastapi import FastAPI
    from ShopDemo import router
    app = FastAPI()
    app.include_router(router)
    return app.openapi()


ITEMS = [{"id": "a", "name": "Máy A", "price": 100, "stock": 3, "_list_path": "/api/shop/products"},
         {"id": "b", "name": "Máy B", "price": 200, "stock": 25, "_list_path": "/api/shop/products"}]
REQ = "Tổng tiền total. Chưa đăng nhập 401. Vượt tồn kho 409. Sản phẩm không tồn tại 404."


def test_expander_builds_distinct_cases_without_llm():
    from ai.expander import build_cases
    cases = build_cases(_shop_spec(), REQ, ITEMS, limit=150)
    assert len(cases) >= 50 and len({c.title for c in cases}) == len(cases)
    assert all((c.technique or "").startswith("rule:") and c.category == "functional" for c in cases)
    assert not any("/bugs" in (s.path or "") or "/reset" in (s.path or "") for c in cases for s in c.steps)


def test_expander_expected_results_follow_real_data():
    from ai.expander import build_cases
    by = {c.title: c for c in build_cases(_shop_spec(), REQ, ITEMS, limit=150)}
    assert by["Đặt 2 Máy A: tổng tiền bằng đơn giá nhân số lượng"].steps[-1].expect["json_contains"] == {"total": 200}
    assert by["Đặt vượt tồn kho Máy A (4) bị từ chối"].steps[-1].expect == {"status": 409}
    assert by["Đặt đúng bằng tồn kho Máy A (3) được chấp nhận"].steps[-1].body["items"][0]["quantity"] == 3
    assert not any("tồn kho Máy B (2" in t for t in by)     # 25 vượt tối đa 20 của API: không suy ra biên tồn kho
    long_name = by["POST /api/shop/checkout: customer_name dài hơn tối đa (101 ký tự)"].steps[-1]
    assert len(long_name.body["customer_name"]) == 101 and long_name.expect == {"status": 422}


def test_expander_limit_mixes_groups_and_never_repeats_to_pad():
    from ai.expander import build_cases
    few = build_cases(_shop_spec(), REQ, ITEMS, limit=12)
    assert len(few) == 12 and len({c.technique for c in few}) >= 3
    assert build_cases(None, REQ, ITEMS, limit=100) == []


def test_large_count_uses_small_ai_core_and_survives_ai_outage(tmp_path, monkeypatch):
    from ai import agents
    from backend import db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "e.db")
    db.init_db()

    class Down:
        name, model, last_used = "down", "m", None

        def complete_json(self, s, u):
            raise RuntimeError("hết hạn mức")
    r = agents.generate_pipeline(REQ, "http://x/shop", count=100, spec=_shop_spec(), provider=Down(), economy=True, items=ITEMS, lead=False, ai_review_enabled=False)
    rules = [c for c in r["cases"] if c.id.split("-")[1].endswith("X")]
    assert len(rules) == len(r["cases"]) >= 50 and r["stats"]["rule_cases"] == len(rules) and r["stats"]["ai_cases"] == 0
    assert any("Writer lỗi" in w for w in r["warnings"]) and any(t["agent"] == "expander" for t in r["trace"])
    assert len(r["cases"]) < 100 and any("không lặp lại" in w for w in r["warnings"])     # báo thật khi không đủ số


def test_ai_only_reviews_ai_written_cases_and_core_is_capped(tmp_path, monkeypatch):
    from ai import agents
    from backend import db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "e2.db")
    db.init_db()
    asked = []

    class Fake:
        name, model, last_used = "f", "m", None

        def complete_json(self, system, user):
            asked.append(user)
            if "test_cases" in system and "Generate between" in user:
                assert "between 10 and 10" in user
                return {"test_cases": [{"title": f"Kịch bản AI số {i}", "type": "api",
                                        "steps": [{"method": "GET", "path": "/api/shop/products", "expect": {"status": 200, "json_contains": [{"id": "a"}]}}]} for i in range(10)]}
            return {"criteria": [], "reviews": []}
    r = agents.generate_pipeline(REQ, "http://x/shop", count=60, spec=_shop_spec(), provider=Fake(), economy=True, items=ITEMS, lead=False, auto_fix=False)
    assert len(r["cases"]) == 60 and r["stats"]["rule_cases"] == 50 and r["stats"]["ai_cases"] == 10
    review_prompts = [u for u in asked if "Test cases:" in u]
    assert review_prompts and not any("X-0" in u for u in review_prompts)    # AI không đọc kịch bản theo luật


def test_cache_returns_same_answer_without_calling_llm(tmp_path, monkeypatch):
    from ai.llm_cache import CachedLLM
    from backend import db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "c.db")
    db.init_db()
    base = _Scripted({"x": 1}, {"x": 2})
    c = CachedLLM(base)
    assert c.complete_json("s", "u") == {"x": 1} and c.complete_json("s", "u") == {"x": 1}
    assert base.calls == 1 and c.hits == 1 and c.misses == 1
    assert c.complete_json("s", "khác") == {"x": 2} and base.calls == 2      # đầu vào đổi thì gọi lại


def test_failed_llm_answer_is_not_cached(tmp_path, monkeypatch):
    from ai.llm_cache import CachedLLM
    from backend import db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "c2.db")
    db.init_db()

    class Flaky:
        name, model, calls = "f", "m", 0

        def complete_json(self, s, u):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("429")
            return {"ok": 1}
    c = CachedLLM(Flaky())
    with pytest.raises(RuntimeError):
        c.complete_json("s", "u")
    assert c.complete_json("s", "u") == {"ok": 1}


def test_rule_cases_are_not_counted_as_ai_metrics():
    from backend.quality_routes import _is_ai
    assert _is_ai("TC-AB12-01") and _is_ai("TC-AB12S-01") and not _is_ai("TC-AB12X-001") and not _is_ai("TC-DEMO-01")


def test_verifier_classifies_rule_case_without_llm(monkeypatch):
    import ai.verifier as v
    from backend.models import TestCase
    monkeypatch.setattr(v, "run_api_test", lambda tc, base, **k: [{"status": "failed", "error_msg": "expected status 422, got 201", "actual_status": 201}])

    def boom(*a, **k):
        raise AssertionError("không được gọi AI")
    tc = TestCase(id="TC-AAAAX-001", title="x", type="api", technique="rule:boundary", steps=[{"method": "GET", "path": "/x"}])
    monkeypatch.setattr(v, "classify_failures", lambda items, *a, **k: [] if not items else boom())
    out = v.verify([tc], "http://x", "http://x")
    assert out[tc.id]["status"] == "app_bug" and "Nghi vấn" in out[tc.id]["detail"]


# ---------- Ổn định ----------
def test_runs_on_same_target_are_serialized(client, monkeypatch):
    import threading
    import time as _t
    _seed([_case(1), _case(2)])
    active, peak, lock = {"n": 0}, {"n": 0}, threading.Lock()

    def fake(tc, base, **kw):
        with lock:
            active["n"] += 1
            peak["n"] = max(peak["n"], active["n"])
        _t.sleep(0.05)
        with lock:
            active["n"] -= 1
        return [{"data_set": "-", "expected": "accept", "status": "passed", "error_msg": "", "duration_ms": 1}]
    monkeypatch.setattr("ai.quick_runner.run_api_test", fake)
    monkeypatch.setattr("backend.ai_routes._target", lambda url: ("http://testserver", None, ""))
    monkeypatch.setattr("backend.ai_routes._shop_reset_hook", lambda base: None)

    def call():
        assert client.post("/api/ai/run", json={"test_case_ids": ["TC-1", "TC-2"], "classify": False}).status_code == 200
    threads = [threading.Thread(target=call) for _ in range(3)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert peak["n"] == 1


def test_verifier_crash_keeps_generated_cases(tmp_path, monkeypatch):
    from ai import agents
    from backend import db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "v.db")
    db.init_db()

    def boom(batch):
        raise RuntimeError("Executable doesn't exist")
    r = agents.generate_pipeline(REQ, "http://x/shop", count=30, spec=_shop_spec(), provider=None, llm_enabled=False,
                                 economy=True, items=ITEMS, lead=False, verifier=boom)
    assert len(r["cases"]) == 30 and any("Không chạy thử được" in w for w in r["warnings"])
    assert any(t["agent"] == "verifier" and t["status"] == "error" for t in r["trace"])


def test_unexpected_error_returns_json_without_details(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from backend.main import app

    def boom(*a, **k):
        raise RuntimeError("bi-mat-noi-bo")
    monkeypatch.setattr("backend.main.get_conn", boom)
    r = TestClient(app, raise_server_exceptions=False).get("/api/test-cases")
    assert r.status_code == 500 and "bi-mat-noi-bo" not in r.text and r.json()["detail"]


def test_login_format_rejection_accepts_401():
    from ai.expander import build_cases
    by = {c.title: c for c in build_cases(_shop_spec(), REQ, ITEMS, limit=150)}
    assert 401 in by["POST /api/shop/auth/login: email thiếu @"].steps[-1].expect["status_in"]
    assert by["POST /api/shop/auth/register: email thiếu @"].steps[-1].expect == {"status": 422}


def test_connection_failure_is_retried_once_not_reported_as_fail(monkeypatch):
    import httpx
    from ai import quick_runner as q
    calls = {"n": 0}

    class Client:
        def __init__(self, *a, **k):
            pass

        def request(self, *a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                raise httpx.ReadTimeout("timed out")
            return httpx.Response(200, json={"ok": 1})
    monkeypatch.setattr(q, "_Prefixed", Client)
    r = q.run_api_test(_case(1), "http://x")
    assert r[0]["status"] == "passed" and r[0]["retried"] is True and calls["n"] == 2


def test_persistent_connection_failure_still_fails_and_reset_error_is_handled(monkeypatch):
    import httpx
    from ai import quick_runner as q

    class Client:
        def __init__(self, *a, **k):
            pass

        def request(self, *a, **k):
            raise httpx.ConnectError("refused")
    monkeypatch.setattr(q, "_Prefixed", Client)
    r = q.run_api_test(_case(1), "http://x")
    assert r[0]["status"] == "failed" and r[0]["connection_error"] and r[0]["retried"]

    def bad_reset():
        raise httpx.ReadTimeout("timed out")
    assert q.run_api_test(_case(2), "http://x", before_each=bad_reset)[0]["status"] == "failed"     # không làm đổ cả lượt


def test_exhausted_ai_is_not_waited_for_again_in_the_same_run(tmp_path, monkeypatch):
    from ai.llm_cache import CachedLLM
    from ai.llm_provider import LLMError, WAIT_BUDGET
    from backend import db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "w.db")
    db.init_db()
    seen = []

    class Down:
        name, model = "d", "m"

        def complete_json(self, s, u):
            seen.append(WAIT_BUDGET.get())
            raise LLMError("hết hạn mức")
    c = CachedLLM(Down(), wait_seconds=7)
    with pytest.raises(LLMError):
        c.complete_json("s", "1")
    with pytest.raises(LLMError):
        c.complete_json("s", "2")
    assert seen == [7] and WAIT_BUDGET.get() is None    # chỉ gọi thật một lần, có giới hạn chờ, không rò rỉ giới hạn


def test_fallback_gives_up_within_wait_budget():
    import time as _t
    from ai.llm_provider import FallbackProvider, LLMProvider, RateLimitError, LLMError, WAIT_BUDGET

    class Limited(LLMProvider):
        name, default_model = "x", "m"

        def _complete(self, s, u, j):
            raise AssertionError

        def complete(self, s, u, json_mode=False):
            raise RateLimitError("429", 500)
    p = FallbackProvider([Limited()])
    token = WAIT_BUDGET.set(0.2)
    t = _t.time()
    with pytest.raises(LLMError):
        p.complete("s", "u")
    WAIT_BUDGET.reset(token)
    assert _t.time() - t < 3


def test_cache_can_be_skipped_but_is_still_written(tmp_path, monkeypatch):
    from ai.llm_cache import CachedLLM
    from backend import db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "s.db")
    db.init_db()
    base = _Scripted({"x": 1}, {"x": 2})
    assert CachedLLM(base, read_cache=False).complete_json("s", "u") == {"x": 1}
    assert CachedLLM(base, read_cache=False).complete_json("s", "u") == {"x": 2}
    assert CachedLLM(base).complete_json("s", "u") == {"x": 2} and base.calls == 2


@pytest.mark.parametrize("count,expected", [(5, 5), (None, 8)])
def test_small_count_falls_back_to_rules_when_ai_is_down(tmp_path, monkeypatch, count, expected):
    from ai import agents
    from backend import db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "s5.db")
    db.init_db()

    class Down:
        name, model, last_used = "d", "m", None

        def complete_json(self, s, u):
            raise RuntimeError("hết hạn mức")
    r = agents.generate_pipeline(REQ, "http://x/shop", count=count, spec=_shop_spec(), provider=Down(), economy=True, items=ITEMS)
    assert len(r["cases"]) == expected and all((c.technique or "").startswith("rule:") for c in r["cases"])
    assert any("Writer lỗi" in w for w in r["warnings"])


def test_small_count_uses_ai_only_when_ai_works(tmp_path, monkeypatch):
    from ai import agents
    from backend import db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "s6.db")
    db.init_db()
    case = {"title": "Xem danh sách sản phẩm đầy đủ", "type": "api",
            "steps": [{"method": "GET", "path": "/api/shop/products", "expect": {"status": 200, "json_contains": [{"id": "a"}]}}]}
    llm = _Scripted({"test_cases": [case] * 1}, {"criteria": [], "reviews": []})
    r = agents.generate_pipeline(REQ, "http://x/shop", count=5, spec=_shop_spec(), provider=llm, economy=True, items=ITEMS, lead=False, auto_fix=False)
    assert not any(t["agent"] == "expander" for t in r["trace"]) and not any("X-" in c.id for c in r["cases"])


def test_hung_llm_call_is_abandoned_and_not_retried(tmp_path, monkeypatch):
    import time as _t
    from ai.llm_cache import CachedLLM
    from ai.llm_provider import LLMError, WAIT_BUDGET
    from backend import db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "h.db")
    db.init_db()
    seen = []

    class Hung:
        name, model = "h", "m"

        def complete_json(self, s, u):
            seen.append(WAIT_BUDGET.get())
            _t.sleep(1.5)
            return {"late": 1}
    c = CachedLLM(Hung(), wait_seconds=9, hard_limit=0.1)
    t0 = _t.time()
    with pytest.raises(LLMError):
        c.complete_json("s", "1")
    with pytest.raises(LLMError):
        c.complete_json("s", "2")
    assert _t.time() - t0 < 1 and seen == [9]     # không chờ hết, không gọi lại, giới hạn chờ vẫn tới được luồng gọi


def test_frontend_is_revalidated_and_navigation_has_only_main_tabs(client):
    r = client.get("/theme.js")
    assert r.headers["cache-control"] == "no-cache"
    for removed in ("quality", "agents", "maintenance", "handbook"):
        page = f"/{removed}.html"
        assert page not in r.text and client.get(page).status_code == 404
        assert page not in client.get("/").text and page not in client.get("/ai.html").text
    assert client.get("/handbook-files/01-tong-quan.md").status_code == 404
    assert 'src="/theme.js?v=' in client.get("/ai.html").text and 'src="/theme.js?v=' in client.get("/").text

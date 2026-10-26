# SPDX-License-Identifier: Apache-2.0
"""Test module AI bằng FakeProvider — không gọi API thật, không cần khoá."""

import json

import pytest

from ai import classifier, data_generator, healing, impact, test_generator, ui_steps
from ai.autopilot import autopilot
from ai.dom import extract_elements
from ai.json_utils import parse_json
from ai.llm_provider import LLMError, LLMProvider, get_provider
from backend.models import TestCase


class FakeProvider(LLMProvider):
    name = "fake"

    def __init__(self, *responses):
        super().__init__(model="fake")
        self.responses = list(responses)
        self.calls = []

    def _complete(self, system, user, json_mode):
        self.calls.append((system, user))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r if isinstance(r, str) else json.dumps(r, ensure_ascii=False)


SHOP_V1 = """<html><body>
<nav><a href="/products" data-testid="nav-products">Sản phẩm</a></nav>
<form><label for="email">Email</label><input id="email" type="email" data-testid="login-email">
<input type="password" placeholder="Mật khẩu"><button type="submit">Đăng nhập</button></form>
<button data-testid="add-to-cart-1">Thêm vào giỏ</button><span data-testid="cart-count">0</span>
<script>var x = "<button>fake</button>";</script></body></html>"""

SHOP_V2 = """<html><body><div class="toolbar">
<span data-testid="cart-count">0</span>
<button class="btn primary">Thêm vào giỏ hàng</button>
<button>Xoá</button></div></body></html>"""


def test_parse_json_variants():
    assert parse_json('{"a": 1}') == {"a": 1}
    assert parse_json('Đây:\n```json\n[1,2]\n```') == [1, 2]
    assert parse_json('blah {"a": {"b": 2}} end') == {"a": {"b": 2}}
    with pytest.raises(ValueError):
        parse_json("không có json")


def test_extract_elements():
    els = extract_elements(SHOP_V1)
    by_testid = {e.testid: e for e in els if e.testid}
    assert by_testid["add-to-cart-1"].role == "button"
    assert by_testid["add-to-cart-1"].name == "Thêm vào giỏ"
    assert by_testid["login-email"].name == "Email"           # lấy từ <label for>
    assert any(e.name == "Mật khẩu" and e.role == "textbox" for e in els)
    assert not any(e.name == "fake" for e in els)               # bỏ qua <script>


def test_generate_test_cases_normalizes_and_assigns_ids():
    fake = FakeProvider({"test_cases": [
        {"title": "Đăng nhập OK", "type": "api", "priority": "HIGH",
         "data_sets": [{"name": "ok", "values": {"email": "a@b.c"}, "expected": "valid"}],
         "steps": [{"method": "post", "path": "api/login", "body": {"email": "{{email}}"},
                    "expect": "200"}]},
        {"title": "Thêm giỏ", "steps": [
            {"action": "GOTO", "url": "/products"},
            {"action": "click", "target": {"testid": "add-to-cart-1", "xpath": "//b"}}]},
    ]})
    cases = test_generator.generate_test_cases("Người dùng đăng nhập", provider=fake)
    assert len(cases) == 2
    a, u = cases
    assert a.steps[0].method == "POST" and a.steps[0].path == "/api/login"
    assert a.steps[0].expect == {"status": 200}
    assert a.priority == "high" and a.data_sets[0].expected == "accept"
    assert u.type == "ui" and u.steps[0].action == "goto"
    assert a.id.startswith("TC-") and a.id != u.id
    assert len(fake.calls) == 1                          # không cần vòng sửa


def test_generate_test_cases_repairs_invalid():
    bad = {"test_cases": [{"title": "Thiếu data", "type": "api",
                           "steps": [{"method": "POST", "path": "/api/login",
                                      "body": {"email": "{{email}}"}, "expect": {"status": 200}}]}]}
    good = {"test_cases": [{"title": "Đủ data", "type": "api",
                            "data_sets": [{"name": "x", "values": {"email": "a@b.c"}}],
                            "steps": [{"method": "POST", "path": "/api/login",
                                       "body": {"email": "{{email}}"}, "expect": {"status": 200}}]}]}
    fake = FakeProvider(bad, good)
    cases = test_generator.generate_test_cases("x", provider=fake)
    assert len(cases) == 1 and cases[0].title == "Đủ data"
    assert "không có data_sets" in fake.calls[1][1]


def test_summarize_openapi():
    spec = {"paths": {"/api/login": {"post": {
        "summary": "Login", "requestBody": {"content": {"application/json": {
            "schema": {"$ref": "#/components/schemas/Login"}}}},
        "responses": {"200": {}, "400": {}}}}},
        "components": {"schemas": {"Login": {"type": "object", "required": ["email"],
                                             "properties": {"email": {"type": "string", "format": "email"}}}}}}
    s = test_generator.summarize_openapi(spec)
    assert "POST /api/login" in s and '"format": "email"' in s and "200, 400" in s


def _login_case():
    return TestCase.model_validate({
        "id": "TC-1", "title": "login", "type": "api",
        "data_sets": [{"name": "ok", "values": {"email": "a@b.c", "password": "x"}}],
        "steps": [{"method": "POST", "path": "/api/login",
                   "body": {"email": "{{email}}", "password": "{{password}}"}, "expect": {"status": 200}}]})


def test_generate_test_data_tokens():
    data_generator.seed(1)
    fake = FakeProvider({"data_sets": [
        {"name": "hop le", "values": {"email": "<faker:email>", "password": "<faker:password>"}, "expected": "accept"},
        {"name": "email_qua_dai", "values": {"email": "<len:255:@demo.com>"}, "expected": "reject"},
        {"name": "email_qua_dai", "values": {"email": "<len:254:@demo.com>"}, "expected": "accept"},
    ]})
    sets = data_generator.generate_test_data(_login_case(), provider=fake)
    assert [s.name for s in sets] == ["hop_le", "email_qua_dai", "email_qua_dai_2"]
    assert "@" in sets[0].values["email"] and "<" not in sets[0].values["password"]
    assert len(sets[1].values["email"]) == 255 and sets[1].values["email"].endswith("@demo.com")
    assert "password" in sets[1].values                   # tự điền field còn thiếu


def test_generate_test_data_falls_back_to_rules():
    sets = data_generator.generate_test_data(_login_case(), provider=FakeProvider(LLMError("hết quota")))
    names = {s.name for s in sets}
    assert "hop_le" in names and "email_rong" in names and "password_qua_ngan" in names
    assert sum(s.expected == "accept" for s in sets) >= 1


def test_ui_steps_adds_goto():
    fake = FakeProvider({"steps": [{"action": "click", "target": {"testid": "add-to-cart-1"}},
                                   {"action": "assert_text", "target": {"testid": "cart-count"}, "expect": "1"}]})
    steps = ui_steps.generate_ui_steps("Thêm vào giỏ", SHOP_V1, url="/products", provider=fake)
    assert steps[0].action == "goto" and steps[0].url == "/products"
    assert "testid=add-to-cart-1" in fake.calls[0][1]      # prompt chứa phần tử đã rút gọn


def test_classify_heuristic_and_ai():
    tc = _login_case()
    r = classifier.classify_failure(tc, {"error_msg": "expected status 400, got 200"},
                                    provider=FakeProvider(RuntimeError("down")))
    assert r["verdict"] == "app_bug" and r["source"] == "heuristic"
    r = classifier.classify_failure(tc, {"passed_on_retry": True}, provider=FakeProvider(
        {"verdict": "FLAKY", "confidence": 2, "explanation": "pass khi chạy lại"}))
    assert r["verdict"] == "flaky" and r["confidence"] == 1.0 and r["source"] == "ai"
    ui = {"id": "U", "title": "u", "type": "ui", "steps": []}
    assert classifier.heuristic(ui, {"error_msg": "Timeout 5000ms waiting for locator('x')"})["verdict"] == "test_broken"


def test_healing_ai_pick_is_validated():
    step = {"action": "click", "target": {"role": "button", "name": "Thêm vào giỏ", "testid": "add-to-cart-1"}}
    fake = FakeProvider({"index": 0, "confidence": 0.9, "reason": "Nút đổi tên"})
    r = healing.suggest_locator(step, SHOP_V2, provider=fake)
    assert r["target"]["role"] == "button" and r["target"]["name"] == "Thêm vào giỏ hàng"
    # index ngoài phạm vi → không bịa locator
    r = healing.suggest_locator(step, SHOP_V2, provider=FakeProvider({"index": 99}))
    assert r["target"] is None


def test_healing_fuzzy_fallback():
    step = {"action": "click", "target": {"role": "button", "name": "Thêm vào giỏ"}}
    r = healing.suggest_locator(step, SHOP_V2, provider=FakeProvider(LLMError("offline")))
    assert r["source"] == "fuzzy" and r["target"]["name"] == "Thêm vào giỏ hàng"


def test_impact_filters_unknown_ids():
    fake = FakeProvider({"affected": [{"id": "TC-1", "action": "update", "reason": "đổi mã lỗi"},
                                      {"id": "TC-404", "action": "obsolete"}],
                         "uncovered": ["Đăng nhập bằng Google"]})
    r = impact.find_affected_tests("trả 400", "trả 422", [_login_case()], provider=fake)
    assert [a["id"] for a in r["affected"]] == ["TC-1"] and r["uncovered"]


def test_autopilot_with_given_pages(monkeypatch):
    monkeypatch.setattr("ai.autopilot.find_openapi", lambda url: None)
    fake = FakeProvider({"app_summary": "Shop", "test_cases": [
        {"title": "Thêm giỏ", "type": "ui", "steps": [
            {"action": "goto", "url": "/products"},
            {"action": "click", "target": {"testid": "add-to-cart-1"}},
            {"action": "assert_text", "target": {"testid": "cart-count"}, "expect": "1"}]}]})
    r = autopilot("http://shop", provider=fake,
                  pages=[{"path": "/products", "title": "SP", "html": SHOP_V1}])
    assert r["app_summary"] == "Shop" and len(r["test_cases"]) == 1
    assert r["test_cases"][0].id.endswith("U-01")


def test_get_provider_errors(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(LLMError):
        get_provider("groq")
    with pytest.raises(LLMError):
        get_provider("khong-co")


def test_saved_variables_count_as_defined():
    fake = FakeProvider({"test_cases": [{"title": "Xem đơn", "type": "api", "steps": [
        {"method": "POST", "path": "/api/shop/checkout", "body": {"items": []},
         "expect": {"status": 201}, "save": {"order_id": "order_id"}},
        {"method": "GET", "path": "/api/shop/orders/{{order_id}}", "expect": {"status": 200}}]}]})
    cases = test_generator.generate_test_cases("x", provider=fake)
    assert cases[0].steps[0].save == {"order_id": "order_id"}
    # dùng biến trước khi save → lỗi
    bad = {"test_cases": [{"title": "Sai thứ tự", "type": "api", "steps": [
        {"method": "GET", "path": "/o/{{oid}}", "expect": {"status": 200}},
        {"method": "POST", "path": "/o", "save": {"oid": "id"}}]}]}
    with pytest.raises(ValueError):
        test_generator.generate_test_cases("x", provider=FakeProvider(bad, bad))


def test_admin_paths_excluded_from_openapi():
    spec = {"paths": {"/api/shop/products": {"get": {"responses": {"200": {}}}},
                      "/api/shop/bugs/{flag}": {"put": {"responses": {"200": {}}}},
                      "/api/shop/reset": {"post": {"responses": {"200": {}}}}}}
    s = test_generator.summarize_openapi(spec)
    assert "/api/shop/products" in s and "bugs" not in s and "reset" not in s


def test_classifier_detects_unknown_api_path():
    res = {"request": {"path": "/api/login"}, "actual_status": 405, "error_msg": "expected status 200, got 405"}
    r = classifier.heuristic({"type": "api"}, res, ["/api/shop/products", "/api/shop/orders/{order_id}"])
    assert r["verdict"] == "test_broken"
    res2 = {"request": {"path": "/api/shop/orders/99"}, "actual_status": 404, "error_msg": "expected status 200, got 404"}
    assert classifier.heuristic({"type": "api"}, res2, ["/api/shop/orders/{order_id}"])["verdict"] == "app_bug"


def test_quick_runner_substitute_and_contains():
    from ai.quick_runner import json_contains, substitute
    assert substitute({"q": "{{n}}", "s": "id-{{n}}"}, {"n": 3}) == {"q": 3, "s": "id-3"}
    assert json_contains({"total": 100, "items": [{"id": "a"}]}, {"total": 100.0, "items": [{"id": "a", "x": 1}]})
    assert not json_contains({"total": 100}, {"total": 200})


def test_fallback_provider_switches_on_error():
    from ai.llm_provider import FallbackProvider
    first = FakeProvider(LLMError("429 hết quota"))
    second = FakeProvider({"ok": True})
    second.name = "backup"
    fb = FallbackProvider([first, second])
    assert fb.complete_json("s", "u") == {"ok": True} and fb.last_used is second


def test_autopilot_repairs_invalid_cases(monkeypatch):
    monkeypatch.setattr("ai.autopilot.find_openapi", lambda url: None)
    bad = {"app_summary": "Shop", "test_cases": [{"title": "Thiếu target", "type": "ui",
                                                  "steps": [{"action": "click"}]}]}
    good = {"test_cases": [{"title": "Đủ", "type": "ui", "steps": [
        {"action": "goto", "url": "/"}, {"action": "click", "target": {"testid": "add-to-cart-1"}}]}]}
    r = autopilot("http://shop", provider=FakeProvider(bad, good),
                  pages=[{"path": "/", "title": "SP", "html": SHOP_V1}])
    assert len(r["test_cases"]) == 1 and r["app_summary"] == "Shop" and r["warnings"] == []


def test_export_describe_step_and_workbook():
    from backend.export import describe_step
    from backend.models import Step
    api = Step(method="POST", path="/api/x", body={"a": 1}, expect={"status": 201, "json_contains": {"total": 5}},
               save={"oid": "order_id"})
    action, target, data, expected = describe_step(api)
    assert (action, target) == ("POST", "/api/x") and "HTTP 201" in expected and "oid" in expected
    ui = Step(action="click", target={"role": "button", "name": "Mua"})
    assert describe_step(ui)[1] == 'button "Mua"'
    assert describe_step(Step(action="assert_text", target={"testid": "t"}, expect="1"))[3] == 'hiển thị "1"'


def test_generate_many_plans_then_batches(monkeypatch):
    monkeypatch.setattr(test_generator, "BATCH_SIZE", 3)
    plan = {"scenarios": [{"title": f"Kịch bản {i}", "type": "api"} for i in range(1, 8)]}

    def batch(n0, n):
        return {"test_cases": [{"title": f"Kịch bản {i}", "type": "api",
                                "steps": [{"method": "GET", "path": "/x", "expect": {"status": 200}}]}
                               for i in range(n0, n0 + n)]}

    monkeypatch.setenv("AI_PARALLEL", "1")      # chạy tuần tự để FakeProvider trả lời đúng thứ tự
    fake = FakeProvider(plan, batch(1, 3), batch(4, 3), batch(7, 1))
    cases = test_generator.generate_test_cases("yêu cầu", count=7, provider=fake)
    assert [c.title for c in cases] == [f"Kịch bản {i}" for i in range(1, 8)]
    assert cases[-1].id.endswith("-07") and len({c.id for c in cases}) == 7


def test_fallback_cools_down_rate_limited_provider():
    from ai.llm_provider import FallbackProvider, RateLimitError
    first = FakeProvider(RateLimitError("429 hết hạn mức"), {"never": True})
    second = FakeProvider({"ok": 1}, {"ok": 2})
    second.name = "backup"
    fb = FallbackProvider([first, second])
    assert fb.complete_json("s", "u") == {"ok": 1}
    assert fb.complete_json("s", "u") == {"ok": 2}      # lần 2 bỏ qua provider đang nghỉ
    assert len(first.calls) == 1


def test_code_in_data_is_rejected_and_tokens_resolved():
    bad = {"test_cases": [{"title": "Tên quá dài", "type": "api",
                           "steps": [{"method": "POST", "path": "/x", "body": {"name": "a\".repeat(101)"},
                                      "expect": {"status": 422}}]}]}
    good = {"test_cases": [{"title": "Tên quá dài", "type": "api",
                            "steps": [{"method": "POST", "path": "/x", "body": {"name": "<len:101>",
                                       "email": "<len:255:@demo.com>"}, "expect": {"status": 422}}]}]}
    fake = FakeProvider(bad, good)
    cases = test_generator.generate_test_cases("x", provider=fake)
    body = cases[0].steps[0].body
    assert len(body["name"]) == 101 and len(body["email"]) == 255 and body["email"].endswith("@demo.com")
    assert "repeat" in fake.calls[1][1]        # lỗi được gửi lại cho AI sửa


def test_classifier_flags_code_in_data():
    tc = {"type": "api", "steps": [{"method": "POST", "path": "/x", "body": {"a": "b\".repeat(301)}"}}]}
    r = classifier.heuristic(tc, {"error_msg": "expected status 422, got 201", "actual_status": 201})
    assert r["verdict"] == "test_broken"


def test_backend_app_imports_and_routes_exist():
    # Bắt lỗi cú pháp / import trong backend (route AI, export) mà các test khác không chạm tới
    from backend.main import app
    paths = set(app.openapi()["paths"])
    assert {"/api/ai/run", "/api/ai/generate", "/api/ai/inspect", "/api/export/test-cases.xlsx"} <= paths

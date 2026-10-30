# SPDX-License-Identifier: Apache-2.0
"""Sinh kịch bản bảo mật và hiệu năng từ OpenAPI, không cần AI nên luôn chạy được.

Chỉ dùng trên hệ thống được phép kiểm thử. Payload chỉ để chứng minh điểm yếu, không phá dữ liệu;
số request có giới hạn trong ai/quick_runner.py.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from ai.test_generator import is_excluded
from backend.models import Step, TestCase

SQLI = "' OR '1'='1' --"
XSS = "<script>alert('testpilot')</script>"
LEAKS = ["traceback", "sqlite3.", "syntax error", "stack trace", "at java.", "werkzeug"]
SENSITIVE = re.compile(r"checkout|order|account|profile|/me\b|admin|payment|invoice|cart|user", re.I)
PASSWORD = "TestPilot#2026"


def _resolve(schema: dict, spec: dict, depth: int = 0) -> dict:
    if depth > 4 or not isinstance(schema, dict):
        return {}
    if "$ref" in schema:
        return _resolve(spec.get("components", {}).get("schemas", {}).get(schema["$ref"].split("/")[-1], {}), spec, depth + 1)
    if "anyOf" in schema:
        return _resolve(next((s for s in schema["anyOf"] if s.get("type") != "null"), {}), spec, depth + 1)
    return schema


def _value(name: str, schema: dict, spec: dict, ids: dict[str, str]):
    s = _resolve(schema, spec)
    kind = s.get("type")
    if kind == "object" or "properties" in s:
        return {k: _value(k, v, spec, ids) for k, v in (s.get("properties") or {}).items()
                if k in (s.get("required") or []) or "default" not in v}
    if kind == "array":
        return [_value(name, s.get("items") or {}, spec, ids)]
    if kind == "integer" or kind == "number":
        return max(int(s.get("minimum", 1)), 1)
    if kind == "boolean":
        return True
    low = name.lower()
    if "email" in low:
        return "{{$email}}"
    if "pass" in low:
        return PASSWORD
    if low.endswith("id") and ids.get("id"):
        return ids["id"]
    if "phone" in low:
        return "0901234567"
    n = max(int(s.get("minLength", 0)), 8)
    return ("TestPilot security check" if n <= 24 else "x" * n)[:max(int(s.get("maxLength", 200)), n)]


def _body_schema(op: dict) -> dict | None:
    return ((op.get("requestBody") or {}).get("content", {}).get("application/json", {}) or {}).get("schema")


def _string_fields(body, prefix=()) -> list[tuple]:
    out = []
    if isinstance(body, dict):
        for k, v in body.items():
            if isinstance(v, str) and "{{" not in v and not re.search("pass", k, re.I):
                out.append(prefix + (k,))
            elif isinstance(v, (dict, list)):
                out += _string_fields(v, prefix + (k,))
    elif isinstance(body, list) and body:
        out += _string_fields(body[0], prefix + (0,))
    return out


def _with(body, path: tuple, value):
    import copy
    b = copy.deepcopy(body)
    cur = b
    for key in path[:-1]:
        cur = cur[key]
    cur[path[-1]] = value
    return b


def _find(spec: dict, pattern: str, method: str = "post") -> str | None:
    for p, ops in spec.get("paths", {}).items():
        if method in ops and re.search(pattern, p, re.I) and not is_excluded(p):
            return p
    return None


def _session_steps(spec: dict, ids: dict[str, str]) -> list[Step]:
    """Các bước tạo phiên đăng nhập, nếu hệ thống có API đăng ký."""
    reg = _find(spec, r"regist|signup|sign-up")
    if not reg:
        return []
    schema = _body_schema(spec["paths"][reg]["post"]) or {}
    return [Step(method="POST", path=reg, body=_value("body", schema, spec, ids), expect={"status_lt": 300})]


def _tc(title: str, technique: str, steps: list[Step], *, priority: str = "high", category: str = "security") -> TestCase:
    return TestCase(id="TC-000", title=title, type="api", priority=priority, category=category,
                    technique=technique, steps=steps)


def build_security_cases(spec: dict | None, url: str, sample_ids: dict[str, str] | None = None,
                         max_endpoints: int = 5) -> list[TestCase]:
    ids = sample_ids or {}
    cases: list[TestCase] = []
    page = urlparse(url).path or "/"
    cases.append(_tc(f"Trang {page} có đủ header bảo mật", "OWASP A05", [Step(
        method="GET", path=page, expect={"status_lt": 500, "headers": ["X-Content-Type-Options", "X-Frame-Options"]})],
        priority="medium"))
    cases.append(_tc("Lỗi 404 không để lộ thông tin nội bộ", "OWASP A05", [Step(
        method="GET", path="/__testpilot_khong_ton_tai__", expect={"status_lt": 500, "not_contains": LEAKS})],
        priority="medium"))
    if not spec:
        return cases

    session = _session_steps(spec, ids)
    writes = [(p, m, op) for p, ops in spec.get("paths", {}).items() if not is_excluded(p)
              for m, op in ops.items() if m in ("post", "put", "patch") and _body_schema(op)]
    probed = [w for w in writes if not re.search(r"logout|signout", w[0], re.I)][:max_endpoints]
    for path, method, op in probed:
        body = _value("body", _body_schema(op), spec, ids)
        fields = _string_fields(body)
        need_session = bool(SENSITIVE.search(path)) and not re.search(r"regist|login|signup", path, re.I)
        prefix = list(session) if need_session else []
        m = method.upper()
        if fields:
            f = fields[0]
            cases.append(_tc(f"{m} {path}: chuỗi SQL injection không gây lỗi máy chủ", "OWASP A03", prefix + [Step(
                method=m, path=path, body=_with(body, f, SQLI), expect={"status_lt": 500, "not_contains": LEAKS})]))
            cases.append(_tc(f"{m} {path}: mã script không bị phản chiếu vào HTML", "OWASP A03", prefix + [Step(
                method=m, path=path, body=_with(body, f, XSS), expect={"status_lt": 500, "not_reflected_html": XSS})]))
            cases.append(_tc(f"{m} {path}: dữ liệu rất dài không gây lỗi máy chủ", "OWASP A04", prefix + [Step(
                method=m, path=path, body=_with(body, f, "A" * 20000), expect={"status_lt": 500, "not_contains": LEAKS})],
                priority="medium"))
        cases.append(_tc(f"{m} {path}: sai kiểu dữ liệu không gây lỗi máy chủ", "OWASP A04", prefix + [Step(
            method=m, path=path, body={k: {"$ne": None} for k in (body if isinstance(body, dict) else {})},
            expect={"status_lt": 500, "not_contains": LEAKS})], priority="medium"))

    for p, ops in spec.get("paths", {}).items():
        if is_excluded(p) or not SENSITIVE.search(p) or re.search(r"regist|login|signup|logout|product", p, re.I):
            continue
        for m, op in ops.items():
            if m not in ("get", "post", "put", "patch", "delete") or "{" in p:
                continue
            schema = _body_schema(op)
            body = _value("body", schema, spec, ids) if schema else None
            cases.append(_tc(f"{m.upper()} {p} từ chối người chưa đăng nhập", "OWASP A01", [Step(
                method=m.upper(), path=p, body=body, expect={"status_in": [401, 403]})]))

    idor = _idor_case(spec, ids, session)
    if idor:
        cases.append(idor)

    login = _find(spec, r"login|signin|sign-in")
    if login:
        schema = _body_schema(spec["paths"][login]["post"]) or {}
        wrong = {k: ("sai-mat-khau-demo" if "pass" in k.lower() else "khong-ton-tai@example.com")
                 for k in _value("body", schema, spec, ids)}
        cases.append(_tc("Đăng nhập sai liên tiếp phải bị giới hạn", "OWASP A07", [Step(
            method="POST", path=login, body=wrong, perf={"requests": 8, "concurrency": 1, "min_blocked": 1})]))
    if session:
        cases.append(_tc("Cookie phiên có HttpOnly và SameSite", "OWASP A07", [
            session[0].model_copy(update={"expect": {"status_lt": 300, "cookie_flags": ["httponly", "samesite"]}})]))
    return cases


def _idor_case(spec: dict, ids: dict[str, str], session: list[Step]) -> TestCase | None:
    """Người A tạo tài nguyên, đăng xuất, rồi đọc lại theo ID: phải bị từ chối."""
    logout = _find(spec, r"logout|signout|sign-out")
    if not (session and logout):
        return None
    for path, ops in spec.get("paths", {}).items():
        m = re.search(r"\{(\w+)\}", path)
        if not m or "get" not in ops or is_excluded(path) or not SENSITIVE.search(path):
            continue
        creator = _find(spec, re.split(r"/\{", path)[0].rstrip("/").split("/")[-1].rstrip("s")) or _find(spec, r"checkout|create")
        if not creator or not _body_schema(spec["paths"][creator]["post"]):
            continue
        var = m.group(1)
        body = _value("body", _body_schema(spec["paths"][creator]["post"]), spec, ids)
        return _tc(f"Người chưa đăng nhập không đọc được dữ liệu qua {path}", "OWASP A01 IDOR", [
            *session,
            Step(method="POST", path=creator, body=body, expect={"status_lt": 300}, save={var: var}),
            Step(method="POST", path=logout, expect={"status_lt": 300}),
            Step(method="GET", path=path.replace("{" + var + "}", "{{" + var + "}}"), expect={"status_in": [401, 403, 404]}),
        ])
    return None


def build_performance_cases(spec: dict | None, url: str, max_endpoints: int = 3, p95_ms: int | None = None) -> list[TestCase]:
    """p95_ms: ngưỡng nêu trong yêu cầu; không có thì dùng ngưỡng mặc định."""
    page = urlparse(url).path or "/"
    page_limit, api_limit = p95_ms or 1500, p95_ms or 800
    cases = [_tc(f"Tải trang {page}: p95 dưới {page_limit}ms", "smoke", [Step(
        method="GET", path=page, perf={"requests": 20, "concurrency": 5, "p95_ms": page_limit, "max_error_rate": 0})],
        priority="medium", category="performance")]
    if not spec:
        return cases
    reads = [p for p, ops in spec.get("paths", {}).items() if "get" in ops and "{" not in p and not is_excluded(p)
             and not re.search(r"/me\b|auth", p)][:max_endpoints]
    for p in reads:
        cases.append(_tc(f"GET {p}: p95 dưới {api_limit}ms khi 5 luồng đồng thời", "smoke", [Step(
            method="GET", path=p, perf={"requests": 30, "concurrency": 5, "p95_ms": api_limit, "max_error_rate": 0})],
            priority="medium", category="performance"))
    login = _find(spec, r"login|signin")
    if login:
        reg = _find(spec, r"regist|signup")
        if reg:
            body = _value("body", _body_schema(spec["paths"][reg]["post"]) or {}, spec, {})
            cases.append(_tc("Đăng nhập phản hồi trong 1500ms", "smoke", [
                Step(method="POST", path=reg, body=body, expect={"status_lt": 300}),
                Step(method="POST", path=login, body={k: v for k, v in body.items() if re.search("email|user|pass", k, re.I)},
                     expect={"status": 200, "max_ms": 1500}),
            ], priority="medium", category="performance"))
    return cases


def sample_ids_from(samples: str) -> dict[str, str]:
    m = re.search(r'"id"\s*:\s*"([^"]+)"', samples or "")
    return {"id": m.group(1)} if m else {}

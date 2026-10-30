# SPDX-License-Identifier: Apache-2.0
"""Agent duyệt kịch bản: luật tự động (không tốn token, luôn chạy) + AI đối chiếu với yêu cầu (tuỳ chọn).

Điểm 0–100. approve: từ 80 và không có lỗi nặng. needs_fix: còn sửa được. reject: dưới 50.
Điểm là tín hiệu hỗ trợ; người duyệt có quyết định cuối cùng (bảng reviews, cột decision).
"""

from __future__ import annotations

import json
import re

from ai import prompts
from ai.classifier import _path_match
from ai.llm_provider import LLMProvider, get_provider
from backend.models import TestCase

_WEIGHT = {"high": 30, "medium": 12, "low": 4}
_CODE = re.compile(r"\.repeat\(|new Array\(|\.join\(")
_FRAGILE_CSS = re.compile(r"nth-child|nth-of-type|:eq\(|>\s*\w+\s*>|\.css-|\.sc-|\[class[*^$]?=")
_SECRET_KEY = re.compile(r"pass|pwd|token|secret|api[_-]?key", re.I)
_SAFE_SECRET = re.compile(r"^(\{\{|<|__)")
_REGISTER = re.compile(r"regist|signup|sign-up|dang-ky", re.I)


def endpoints(spec: dict | None) -> dict[str, set[str]]:
    """{path: {METHOD,...}} từ OpenAPI."""
    out: dict[str, set[str]] = {}
    for path, ops in ((spec or {}).get("paths") or {}).items():
        out[path] = {m.upper() for m in ops if m.lower() in ("get", "post", "put", "patch", "delete")}
    return out


def _operation(spec: dict | None, path: str, method: str) -> dict | None:
    for p, ops in ((spec or {}).get("paths") or {}).items():
        if _path_match(p, path) and method.lower() in ops:
            return ops[method.lower()]
    return None


def _required_fields(spec: dict | None, op: dict | None) -> list[str]:
    schema = ((op or {}).get("requestBody") or {}).get("content", {}).get("application/json", {}).get("schema") or {}
    if "$ref" in schema:
        schema = ((spec or {}).get("components") or {}).get("schemas", {}).get(schema["$ref"].split("/")[-1], {})
    return schema.get("required") or []


def _issue(code: str, severity: str, message: str, step: int | None = None) -> dict:
    return {"code": code, "severity": severity, "message": message, "step": step}


def lint(tc: TestCase, spec: dict | None = None, siblings: list[TestCase] | None = None, signatures: dict | None = None) -> list[dict]:
    """Các luật kiểm tra không cần AI. signatures: {chữ ký: [id]} tính sẵn khi duyệt nhiều kịch bản."""
    issues: list[dict] = []
    paths = endpoints(spec)
    text = tc.model_dump_json()
    if _CODE.search(text):
        issues.append(_issue("R01", "high", "Dữ liệu chứa biểu thức code thay vì giá trị thật."))
    for ds in tc.data_sets:
        for k, v in ds.values.items():
            if _SECRET_KEY.search(k) and isinstance(v, str) and v and not _SAFE_SECRET.match(v) and len(v) >= 12:
                issues.append(_issue("R02", "medium", f"Bộ dữ liệu '{ds.name}' có giá trị bí mật viết thẳng ở '{k}'; "
                                                      "dùng {{password}} hoặc biến chạy."))
    if tc.type == "api":
        _lint_api(tc, spec, paths, issues)
    else:
        _lint_ui(tc, issues)
    if len(tc.title.strip()) < 8:
        issues.append(_issue("R03", "low", "Tiêu đề quá ngắn, không mô tả hành vi được kiểm tra."))
    if signatures is None:
        signatures = {}
        for other in siblings or []:
            signatures.setdefault((other.type, _signature(other)), []).append(other.id)
    twin = next((i for i in signatures.get((tc.type, _signature(tc)), []) if i != tc.id), None)
    if twin:
        issues.append(_issue("R04", "medium", f"Trùng các bước với {twin}."))
    return issues


def _signature(tc: TestCase) -> str:
    steps = [s.model_dump(exclude_none=True) for s in tc.steps]
    return json.dumps([steps, [d.values for d in tc.data_sets]], sort_keys=True, ensure_ascii=False, default=str)


def _lint_api(tc: TestCase, spec, paths, issues) -> None:
    has_login = False
    for i, s in enumerate(tc.steps):
        method, path = (s.method or "").upper(), (s.path or "").split("?")[0]
        exp = s.expect if isinstance(s.expect, dict) else {}
        if not s.perf and not any(exp.get(k) for k in ("status", "status_in", "status_lt", "json_contains", "headers",
                                                       "cookie_flags", "max_ms", "not_contains")):
            issues.append(_issue("R10", "high", "Bước API không kiểm tra kết quả nào.", i))
        if paths and "{{" not in path:
            match = next((p for p in paths if _path_match(p, path)), None)
            is_probe = tc.category == "security" and method == "GET"
            if match is None and not is_probe and not (tc.category == "performance"):
                issues.append(_issue("R11", "high", f"{path} không có trong tài liệu OpenAPI.", i))
            elif match and method not in paths[match]:
                issues.append(_issue("R12", "high", f"{method} không được hỗ trợ trên {match}.", i))
        low = path.lower()
        if any(k in low for k in ("login", "regist", "signup", "sign-in", "signin")):
            has_login = True
        code = exp.get("status")
        op = _operation(spec, path, method) if spec else None
        if op and isinstance(code, int) and 200 <= code < 300 and tc.category == "functional":
            body = s.body or {}
            missing = [f for f in _required_fields(spec, op) if f not in body]
            if missing:
                issues.append(_issue("R13", "high", f"Mong đợi thành công nhưng body thiếu trường bắt buộc: {', '.join(missing)}.", i))
        if _REGISTER.search(low) and isinstance(code, int) and code < 300:
            email = (s.body or {}).get("email")
            if isinstance(email, str) and "{{" not in email:
                issues.append(_issue("R14", "medium", "Đăng ký bằng email cố định sẽ lỗi 409 từ lần chạy thứ hai; dùng {{$email}}.", i))
        if isinstance(code, int) and 200 <= code < 300 and not has_login and tc.category == "functional" \
                and any(k in low for k in ("checkout", "/me", "profile", "account")):
            issues.append(_issue("R15", "high", "Gọi API cần đăng nhập nhưng kịch bản chưa tạo phiên ở bước trước.", i))
    if tc.category == "functional" and len(tc.steps) == 1 \
            and not (tc.steps[0].expect if isinstance(tc.steps[0].expect, dict) else {}).get("json_contains") \
            and 200 <= int((tc.steps[0].expect or {}).get("status") or 0 if isinstance(tc.steps[0].expect, dict) else 0) < 300:
        issues.append(_issue("R16", "low", "Chỉ kiểm tra mã trạng thái; nên kiểm tra thêm nội dung trả về."))


def _lint_ui(tc: TestCase, issues) -> None:
    actions = [s.action for s in tc.steps]
    if not actions or actions[0] != "goto":
        issues.append(_issue("R20", "medium", "Kịch bản UI nên bắt đầu bằng goto để chạy độc lập."))
    if not any(a in ("assert_text", "assert_visible") for a in actions):
        issues.append(_issue("R21", "high", "Kịch bản UI không có bước kiểm chứng kết quả."))
    elif actions[-1] not in ("assert_text", "assert_visible", "wait_for"):
        issues.append(_issue("R22", "medium", "Bước cuối nên kiểm chứng kết quả của thao tác."))
    if len(tc.steps) < 3:
        issues.append(_issue("R23", "low", "Kịch bản quá đơn giản (dưới 3 bước), chưa phải luồng người dùng."))
    for i, s in enumerate(tc.steps):
        t = s.target
        if not t:
            continue
        if t.css and not (t.testid or t.name) and _FRAGILE_CSS.search(t.css):
            issues.append(_issue("R24", "medium", f"Locator css dễ gãy: {t.css}.", i))
        if s.action == "assert_text" and not (s.expect or s.value):
            issues.append(_issue("R25", "high", "assert_text không có nội dung mong đợi.", i))


def score_of(issues: list[dict]) -> tuple[int, str]:
    score = max(0, 100 - sum(_WEIGHT.get(i["severity"], 4) for i in issues))
    has_high = any(i["severity"] == "high" for i in issues)
    verdict = "reject" if score < 50 else "needs_fix" if has_high or score < 80 else "approve"
    return score, verdict


def review_cases(cases: list[TestCase], spec: dict | None = None) -> dict[str, dict]:
    """Duyệt bằng luật: {id: {score, verdict, issues, source}}."""
    out = {}
    signatures: dict = {}
    for other in cases:
        signatures.setdefault((other.type, _signature(other)), []).append(other.id)
    for tc in cases:
        issues = lint(tc, spec, signatures=signatures)
        score, verdict = score_of(issues)
        out[tc.id] = {"score": score, "verdict": verdict, "issues": issues, "source": "rules"}
    return out


def ai_review(cases: list[TestCase], requirement: str, api: str = "", guidance: str = "",
              provider: LLMProvider | None = None, chunk: int = 15) -> dict:
    """AI đối chiếu kịch bản với yêu cầu. Trả về {"reviews": {id: [issue]}, "criteria": [{text, covered_by}]}."""
    llm = provider or get_provider()
    ids = {c.id for c in cases}
    reviews: dict[str, list[dict]] = {}
    criteria: list[dict] = []
    system = prompts.REVIEW_SYSTEM.format(skills=guidance)
    for start in range(0, len(cases), chunk):
        part = cases[start:start + chunk]
        text = "\n".join(_compact(c) for c in part)
        data = llm.complete_json(system, prompts.REVIEW_USER.format(requirement=requirement[:4000], api=api[:3000], cases=text[:9000]))
        if not isinstance(data, dict):
            continue
        for row in data.get("reviews") or []:
            if isinstance(row, dict) and row.get("id") in ids:
                for it in row.get("issues") or []:
                    if isinstance(it, dict) and it.get("message"):
                        sev = it.get("severity") if it.get("severity") in _WEIGHT else "medium"
                        reviews.setdefault(row["id"], []).append(_issue("AI", sev, str(it["message"])))
        for c in data.get("criteria") or []:
            if isinstance(c, dict) and c.get("text"):
                criteria.append({"text": str(c["text"]), "covered_by": [x for x in c.get("covered_by") or [] if x in ids]})
    return {"reviews": reviews, "criteria": _merge_criteria(criteria)}


def _merge_criteria(rows: list[dict]) -> list[dict]:
    merged: dict[str, dict] = {}
    for c in rows:
        key = re.sub(r"\W+", " ", c["text"].lower()).strip()
        if key in merged:
            merged[key]["covered_by"] = sorted(set(merged[key]["covered_by"]) | set(c["covered_by"]))
        else:
            merged[key] = c
    return list(merged.values())


def _compact(tc: TestCase) -> str:
    return json.dumps({"id": tc.id, "title": tc.title, "category": tc.category,
                       "steps": [s.model_dump(exclude_none=True) for s in tc.steps][:8],
                       "data_sets": [{"name": d.name, "expected": d.expected} for d in tc.data_sets][:6]},
                      ensure_ascii=False, default=str)


def merge(review: dict, extra: list[dict]) -> dict:
    """Gộp nhận xét của AI vào kết quả luật và tính lại điểm."""
    issues = review["issues"] + extra
    score, verdict = score_of(issues)
    return {"score": score, "verdict": verdict, "issues": issues, "source": "rules+ai"}

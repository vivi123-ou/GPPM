# SPDX-License-Identifier: Apache-2.0
"""Yêu cầu (user story / OpenAPI) → danh sách TestCase theo schema chung."""

from __future__ import annotations

import hashlib
import json
import os
import re

from pydantic import ValidationError

from ai import prompts
from ai.json_utils import unwrap_list
from ai.llm_provider import LLMProvider, get_provider
from backend.models import TestCase

_PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")
_PLAN_PREFIX = re.compile(r"^\s*\[[a-z]+/[a-z]+(?:/[a-z]*)?\]\s*", re.I)
_PLAN_SUFFIX = re.compile(r"\s+[—–-]\s+(GET|POST|PUT|PATCH|DELETE)\s+/\S*.*$")
DEFAULT_EXCLUDE = ("/api/shop/bugs,/api/shop/reset,/api/requirements,/api/test-cases,/api/runs,"
                   "/api/ai/,/api/export/")


BATCH_SIZE = 10        # số test case mỗi lần gọi AI (câu trả lời dài hơn dễ bị cắt / sai JSON)
MAX_COUNT = 150
PLAN_CHUNK = 25


def generate_test_cases(requirement_text: str, openapi_spec: dict | str | None = None,
                        ui_elements: str | None = None, sample_data: str | None = None,
                        *, min_cases: int = 4,
                        max_cases: int = 10, count: int | None = None, id_prefix: str | None = None,
                        provider: LLMProvider | None = None) -> list[TestCase]:
    """Sinh test case. openapi_spec / ui_elements là ngữ cảnh tuỳ chọn giúp AI dùng
    đúng path API và đúng phần tử UI có thật.

    count: số test case mong muốn. Lớn hơn BATCH_SIZE thì AI lập kế hoạch kịch bản trước
    rồi viết chi tiết theo từng đợt (chạy song song, AI_PARALLEL luồng)."""
    llm = provider or get_provider()
    context = _build_context(openapi_spec, ui_elements, sample_data)
    requirement = requirement_text.strip()
    if count and count > BATCH_SIZE:
        cases = _generate_many(llm, requirement, context, min(count, MAX_COUNT))
    else:
        lo, hi = (count, count) if count else (min_cases, max_cases)
        user = prompts.TEST_CASES_USER.format(requirement=requirement, context=context,
                                              min_cases=lo, max_cases=hi)
        cases, errors = _ask(llm, user)
        if not cases:
            raise ValueError("AI không sinh được test case hợp lệ: " + "; ".join(errors[:3]))

    prefix = id_prefix or _prefix_for(requirement_text)
    width = 3 if len(cases) > 99 else 2
    for i, tc in enumerate(cases, 1):
        tc.id = f"{prefix}-{i:0{width}d}"
    return cases


def _ask(llm: LLMProvider, user: str) -> tuple[list[TestCase], list[str]]:
    """Một lần gọi AI + một lần cho AI tự sửa các case lệch schema."""
    raw = unwrap_list(llm.complete_json(prompts.TEST_CASES_SYSTEM, user), "test_cases")
    cases, errors = _validate_all(raw)
    if errors:
        repair = user + "\n\n" + prompts.REPAIR_USER.format(errors="\n".join(errors))
        try:
            raw2 = unwrap_list(llm.complete_json(prompts.TEST_CASES_SYSTEM, repair), "test_cases")
            cases2, errors2 = _validate_all(raw2)
            if len(cases2) >= len(cases):
                cases, errors = cases2, errors2
        except Exception:
            pass
    return cases, errors


def plan_scenarios(llm: LLMProvider, requirement: str, context: str, count: int) -> list[dict]:
    """AI lập danh sách kịch bản (chỉ tiêu đề + gợi ý) — ngắn nên một lần gọi được cả trăm mục."""
    scenarios: list[dict] = []
    for _ in range(count // PLAN_CHUNK + 3):  # mỗi lượt tối đa PLAN_CHUNK mục để câu trả lời không bị cắt
        need = min(count - len(scenarios), PLAN_CHUNK)
        if need <= 0:
            break
        avoid = ("\nAlready planned (do NOT repeat): " + "; ".join(s["title"] for s in scenarios)
                 if scenarios else "")
        data = llm.complete_json(prompts.PLAN_SYSTEM, prompts.PLAN_USER.format(
            requirement=requirement, context=context, count=need, avoid=avoid[:6000]))
        seen = {s["title"].strip().lower() for s in scenarios}
        for s in unwrap_list(data, "scenarios"):
            title = str((s or {}).get("title", "")).strip() if isinstance(s, dict) else ""
            if title and title.lower() not in seen:
                seen.add(title.lower())
                scenarios.append(s)
    return scenarios[:count]


def _generate_many(llm: LLMProvider, requirement: str, context: str, count: int) -> list[TestCase]:
    from concurrent.futures import ThreadPoolExecutor

    scenarios = plan_scenarios(llm, requirement, context, count)
    if not scenarios:
        raise ValueError("AI không lập được kế hoạch kiểm thử")
    batches = [scenarios[i:i + BATCH_SIZE] for i in range(0, len(scenarios), BATCH_SIZE)]

    def run(batch: list[dict]) -> list[TestCase]:
        lines = "\n".join(f"{i}. title: {s['title']}\n   type: {s.get('type', 'api')} · priority: "
                          f"{s.get('priority', 'medium')} · technique: {s.get('technique', '')} · notes: {s.get('notes', '')}"
                          for i, s in enumerate(batch, 1))
        user = prompts.BATCH_USER.format(requirement=requirement, context=context,
                                         count=len(batch), scenarios=lines)
        try:
            return _ask(llm, user)[0]
        except Exception:
            return []           # một đợt lỗi không làm hỏng cả lượt sinh

    workers = max(1, int(os.getenv("AI_PARALLEL", "3")))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(run, batches))
        # Đợt lỗi / thiếu kịch bản: sinh bù một lần cho các kịch bản còn thiếu trong kế hoạch
        got = {tc.title.strip().lower() for batch in results for tc in batch}
        # AI hay sửa nhẹ tiêu đề nên chỉ sinh bù đúng số còn thiếu, không bù theo từng tiêu đề
        shortfall = count - len(got)
        missing = [s for s in scenarios if s["title"].strip().lower() not in got][:max(shortfall, 0)]
        if missing:
            retry = [missing[i:i + BATCH_SIZE] for i in range(0, len(missing), BATCH_SIZE)]
            results += list(pool.map(run, retry))
    cases, seen = [], set()
    for batch in results:                    # giữ thứ tự kế hoạch, bỏ trùng tiêu đề
        for tc in batch:
            key = tc.title.strip().lower()
            if key not in seen:
                seen.add(key)
                cases.append(tc)
    if not cases:
        raise ValueError("AI không sinh được test case hợp lệ ở mọi đợt")
    return cases[:count]


def _build_context(openapi_spec, ui_elements, sample_data=None) -> str:
    parts = []
    if openapi_spec:
        parts.append("OpenAPI spec of the system under test (summarised):\n" + summarize_openapi(openapi_spec))
    if sample_data:
        parts.append("Real data currently in the system (use these existing IDs/values in tests):\n"
                     + sample_data[:4000])
    if ui_elements:
        parts.append("UI elements available:\n" + ui_elements[:6000])
    return "\n\n".join(parts)


def excluded_paths() -> list[str]:
    """API không được sinh test: API quản trị của Demo Shop (bật bug, reset) và API của
    chính TestPilot. Ghi đè bằng AI_EXCLUDE_PATHS="/a,/b"."""
    raw = os.getenv("AI_EXCLUDE_PATHS", DEFAULT_EXCLUDE)
    return [p.strip() for p in raw.split(",") if p.strip()]


def is_excluded(path: str) -> bool:
    return any(path.startswith(p) for p in excluded_paths())


def summarize_openapi(spec: dict | str, limit: int = 8000) -> str:
    """Rút gọn OpenAPI: method, path, body schema, response codes. Giảm token đáng kể."""
    if isinstance(spec, str):
        try:
            spec = json.loads(spec)
        except json.JSONDecodeError:
            return spec[:limit]
    lines = []
    schemas = spec.get("components", {}).get("schemas", {})
    for path, ops in spec.get("paths", {}).items():
        if is_excluded(path):
            continue
        for method, op in ops.items():
            if method.lower() not in ("get", "post", "put", "patch", "delete"):
                continue
            line = f"{method.upper()} {path}"
            if op.get("summary"):
                line += f" — {op['summary']}"
            body = (op.get("requestBody", {}).get("content", {})
                    .get("application/json", {}).get("schema"))
            if body:
                line += f"\n  body: {json.dumps(_resolve(body, schemas), ensure_ascii=False)}"
            codes = ", ".join(op.get("responses", {}).keys())
            if codes:
                line += f"\n  responses: {codes}"
            lines.append(line)
    return "\n".join(lines)[:limit] or json.dumps(spec)[:limit]


def _resolve(schema: dict, schemas: dict, depth: int = 0):
    if depth > 3 or not isinstance(schema, dict):
        return schema
    if "$ref" in schema:
        return _resolve(schemas.get(schema["$ref"].split("/")[-1], {}), schemas, depth + 1)
    if schema.get("type") == "object" or "properties" in schema:
        return {"required": schema.get("required", []),
                "properties": {k: _short(v, schemas, depth) for k, v in schema.get("properties", {}).items()}}
    return schema


def _short(prop: dict, schemas: dict, depth: int):
    prop = _resolve(prop, schemas, depth + 1)
    if not isinstance(prop, dict):
        return prop
    keep = ("type", "format", "minLength", "maxLength", "minimum", "maximum", "enum", "pattern",
            "minItems", "maxItems", "properties", "required")
    out = {k: v for k, v in prop.items() if k in keep} or prop
    if isinstance(prop.get("items"), dict):     # mảng: mô tả luôn phần tử bên trong
        out["items"] = _short(prop["items"], schemas, depth + 1)
    return out


def _validate_all(raw: list) -> tuple[list[TestCase], list[str]]:
    cases, errors = [], []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            errors.append(f"#{i}: không phải object")
            continue
        try:
            tc = TestCase.model_validate(normalize(item))
            _check_semantics(tc)
            cases.append(_resolve_tokens(tc))
        except (ValidationError, ValueError) as e:
            errors.append(f"#{i} ({item.get('title', '?')}): {str(e)[:300]}")
    return cases, errors


def normalize(item: dict) -> dict:
    """Sửa các lỗi vặt LLM hay mắc trước khi validate."""
    item = dict(item)
    item.setdefault("id", "TC-000")
    item.setdefault("title", "Test case")
    # AI đôi khi chép cả nhãn kế hoạch vào tiêu đề: "[api/high/happy] Tiêu đề — POST /x with …"
    title = _PLAN_PREFIX.sub("", str(item["title"])).strip()
    item["title"] = _PLAN_SUFFIX.sub("", title).strip() or title
    steps = [s for s in item.get("steps") or [] if isinstance(s, dict)]
    if "type" not in item or item["type"] not in ("api", "ui"):
        item["type"] = "api" if any(s.get("method") for s in steps) else "ui"
    if str(item.get("priority", "")).lower() not in ("low", "medium", "high"):
        item["priority"] = "medium"
    else:
        item["priority"] = item["priority"].lower()

    allowed_step_keys = {"method", "path", "headers", "body", "expect", "save",
                         "action", "url", "target", "value"}
    clean_steps = []
    for s in steps:
        s = {k: v for k, v in s.items() if k in allowed_step_keys and v is not None}
        if s.get("method"):
            s["method"] = s["method"].upper()
            if s.get("path") and not s["path"].startswith("/"):
                s["path"] = "/" + s["path"]
            exp = s.get("expect")
            if isinstance(exp, (int, str)) and str(exp).isdigit():
                s["expect"] = {"status": int(exp)}
            elif isinstance(exp, dict) and isinstance(exp.get("status"), str) and exp["status"].isdigit():
                exp["status"] = int(exp["status"])
        if s.get("action"):
            s["action"] = str(s["action"]).lower()
            if isinstance(s.get("target"), str):
                s["target"] = {"css": s["target"]}
            if isinstance(s.get("target"), dict):
                s["target"] = {k: v for k, v in s["target"].items()
                               if k in ("testid", "role", "name", "css") and v not in (None, "")}
            if s.get("value") is not None and not isinstance(s["value"], str):
                s["value"] = str(s["value"])
        clean_steps.append(s)
    item["steps"] = clean_steps

    ds = []
    for d in item.get("data_sets") or []:
        if isinstance(d, dict):
            exp = str(d.get("expected", "accept")).lower()
            ds.append({"name": str(d.get("name", f"set_{len(ds) + 1}")),
                       "values": d.get("values") or {},
                       "expected": "reject" if exp in ("reject", "invalid", "fail") else "accept"})
    item["data_sets"] = ds
    return item


_CODE_IN_DATA = re.compile(r"\.repeat\(|new Array\(|\.join\(|\"\s*\*\s*\d+|\\\"\s*\+\s*\\\"")


def _resolve_tokens(tc: TestCase) -> TestCase:
    """Thay <len:N>, <faker:x> trong bước và dữ liệu bằng giá trị thật (chuỗi đúng độ dài...)."""
    from ai.data_generator import resolve_tokens   # import muộn để tránh vòng lặp import
    for s in tc.steps:
        s.body = resolve_tokens(s.body)
        s.value = resolve_tokens(s.value)
        s.path = resolve_tokens(s.path)
        s.expect = resolve_tokens(s.expect)
    for d in tc.data_sets:
        d.values = resolve_tokens(d.values)
    return tc


def _check_semantics(tc: TestCase) -> None:
    if not tc.steps:
        raise ValueError("không có bước nào")
    if _CODE_IN_DATA.search(tc.model_dump_json()):
        raise ValueError('dữ liệu chứa biểu thức code (vd. "a".repeat(300)); hãy dùng token "<len:N>"')
    for i, s in enumerate(tc.steps):
        if tc.type == "api" and not (s.method and s.path):
            raise ValueError(f"bước {i}: test API cần method và path")
        if tc.type == "ui":
            if not s.action:
                raise ValueError(f"bước {i}: test UI cần action")
            if s.action == "goto" and not s.url:
                raise ValueError(f"bước {i}: goto cần url")
            if s.action not in ("goto", "press") and not (s.target and any(s.target.model_dump().values())):
                raise ValueError(f"bước {i}: {s.action} cần target")
    saved: set[str] = set()
    for i, s in enumerate(tc.steps):
        step_vars = set(_PLACEHOLDER.findall(json.dumps(s.model_dump(exclude_none=True, exclude={"save"}),
                                                        ensure_ascii=False)))
        later = set().union(*[(t.save or {}).keys() for t in tc.steps[i:]])
        if step_vars & later - saved:
            raise ValueError(f"bước {i}: dùng biến {sorted(step_vars & later - saved)} trước khi save")
        saved |= set((s.save or {}).keys())
    used = set(find_placeholders(tc)) - saved
    if used and tc.data_sets:
        for d in tc.data_sets:
            missing = used - set(d.values)
            if missing:
                raise ValueError(f"data set '{d.name}' thiếu biến: {sorted(missing)}")
    elif used and not tc.data_sets:
        raise ValueError(f"có placeholder {sorted(used)} nhưng không có data_sets")


def find_placeholders(tc: TestCase) -> list[str]:
    text = json.dumps([s.model_dump(exclude_none=True) for s in tc.steps], ensure_ascii=False)
    return list(dict.fromkeys(_PLACEHOLDER.findall(text)))


def _prefix_for(text: str) -> str:
    # ID phải duy nhất giữa các yêu cầu vì test_cases.id là PRIMARY KEY
    return "TC-" + hashlib.sha1(text.encode("utf-8")).hexdigest()[:4].upper()

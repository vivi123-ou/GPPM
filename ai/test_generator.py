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
DEFAULT_EXCLUDE = "/api/shop/bugs,/api/shop/reset,/api/requirements,/api/test-cases,/api/runs"


def generate_test_cases(requirement_text: str, openapi_spec: dict | str | None = None,
                        ui_elements: str | None = None, sample_data: str | None = None,
                        *, min_cases: int = 4,
                        max_cases: int = 10, id_prefix: str | None = None,
                        provider: LLMProvider | None = None) -> list[TestCase]:
    """Sinh test case. openapi_spec / ui_elements là ngữ cảnh tuỳ chọn giúp AI dùng
    đúng path API và đúng phần tử UI có thật."""
    llm = provider or get_provider()
    user = prompts.TEST_CASES_USER.format(
        requirement=requirement_text.strip(),
        context=_build_context(openapi_spec, ui_elements, sample_data),
        min_cases=min_cases, max_cases=max_cases)
    raw = unwrap_list(llm.complete_json(prompts.TEST_CASES_SYSTEM, user), "test_cases")

    cases, errors = _validate_all(raw)
    if errors:
        # Cho AI một lần tự sửa các case lệch schema
        repair = user + "\n\n" + prompts.REPAIR_USER.format(errors="\n".join(errors))
        try:
            raw2 = unwrap_list(llm.complete_json(prompts.TEST_CASES_SYSTEM, repair), "test_cases")
            cases2, errors2 = _validate_all(raw2)
            if len(cases2) >= len(cases):
                cases, errors = cases2, errors2
        except Exception:
            pass
    if not cases:
        raise ValueError("AI không sinh được test case hợp lệ: " + "; ".join(errors[:3]))

    prefix = id_prefix or _prefix_for(requirement_text)
    for i, tc in enumerate(cases, 1):
        tc.id = f"{prefix}-{i:02d}"
    return cases


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
            cases.append(tc)
        except (ValidationError, ValueError) as e:
            errors.append(f"#{i} ({item.get('title', '?')}): {str(e)[:300]}")
    return cases, errors


def normalize(item: dict) -> dict:
    """Sửa các lỗi vặt LLM hay mắc trước khi validate."""
    item = dict(item)
    item.setdefault("id", "TC-000")
    item.setdefault("title", "Test case")
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


def _check_semantics(tc: TestCase) -> None:
    if not tc.steps:
        raise ValueError("không có bước nào")
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

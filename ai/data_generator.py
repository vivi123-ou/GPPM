# SPDX-License-Identifier: Apache-2.0
"""Sinh dữ liệu test theo phân vùng tương đương (EP) và giá trị biên (BVA).

AI quyết định phân vùng/biên; Faker điền giá trị thực tế; token <len:N> đảm bảo
độ dài chính xác (LLM đếm ký tự rất kém). Nếu LLM lỗi, dùng bộ luật dự phòng.
"""

from __future__ import annotations

import json
import re

from faker import Faker

from ai import prompts
from ai.json_utils import unwrap_list
from ai.llm_provider import LLMProvider, get_provider
from ai.test_generator import find_placeholders
from backend.models import DataSet, TestCase

_fake = Faker(["vi_VN", "en_US"])
_TOKEN = re.compile(r"<(faker|len):([^<>]+)>")
_SAFE_FAKER = {"email", "safe_email", "free_email", "name", "first_name", "last_name",
               "user_name", "password", "phone_number", "address", "city", "street_address",
               "company", "url", "uuid4", "word", "sentence", "text", "postcode", "country",
               "date", "iso8601", "credit_card_number", "ipv4", "random_int"}


def seed(n: int) -> None:
    """Cố định Faker để kết quả tái lập được (dùng khi demo/test)."""
    Faker.seed(n)


def generate_test_data(test_case: TestCase, requirement_text: str = "", *,
                       fields: list[str] | None = None, min_sets: int = 4, max_sets: int = 10,
                       provider: LLMProvider | None = None) -> list[DataSet]:
    fields = fields or find_placeholders(test_case) or _fields_from_existing(test_case)
    if not fields:
        return list(test_case.data_sets)
    try:
        llm = provider or get_provider()
        user = prompts.TEST_DATA_USER.format(
            test_case=test_case.model_dump_json(exclude_none=True),
            fields=", ".join(fields), requirement=requirement_text or "(none)",
            min_sets=min_sets, max_sets=max_sets)
        raw = unwrap_list(llm.complete_json(prompts.TEST_DATA_SYSTEM, user), "data_sets")
        sets = _to_datasets(raw, fields)
    except Exception:
        sets = []
    if not sets:
        sets = rule_based_data(fields)
    return sets


def _fields_from_existing(tc: TestCase) -> list[str]:
    keys: dict[str, None] = {}
    for d in tc.data_sets:
        keys.update(dict.fromkeys(d.values))
    return list(keys)


def _to_datasets(raw: list, fields: list[str]) -> list[DataSet]:
    out, seen = [], set()
    for i, item in enumerate(raw):
        if not isinstance(item, dict) or not isinstance(item.get("values"), dict):
            continue
        values = {k: resolve_tokens(v) for k, v in item["values"].items()}
        for f in fields:                       # đảm bảo đủ biến cho placeholder
            values.setdefault(f, _valid_value(f))
        name = re.sub(r"\W+", "_", str(item.get("name") or f"set_{i + 1}")).strip("_").lower()
        key = json.dumps(values, sort_keys=True, ensure_ascii=False, default=str)
        if key in seen:
            continue
        seen.add(key)
        while name in {d.name for d in out}:
            name += "_2"
        exp = str(item.get("expected", "accept")).lower()
        out.append(DataSet(name=name, values=values,
                           expected="reject" if exp in ("reject", "invalid") else "accept"))
    if out and not any(d.expected == "accept" for d in out):
        out.insert(0, DataSet(name="hop_le", values={f: _valid_value(f) for f in fields}))
    return out


def resolve_tokens(value):
    """Thay <faker:x> và <len:N[:suffix]> trong chuỗi (đệ quy với dict/list)."""
    if isinstance(value, dict):
        return {k: resolve_tokens(v) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_tokens(v) for v in value]
    if not isinstance(value, str):
        return value
    whole = _TOKEN.fullmatch(value.strip())
    if whole and whole.group(1) == "faker" and whole.group(2).strip() == "random_int":
        return _fake.random_int(1, 100)       # giữ kiểu số
    return _TOKEN.sub(_replace, value)


def _replace(m: re.Match) -> str:
    kind, arg = m.group(1), m.group(2).strip()
    if kind == "len":
        n_str, _, suffix = arg.partition(":")
        try:
            n = max(0, min(int(n_str), 10000))
        except ValueError:
            return m.group(0)
        return "a" * max(0, n - len(suffix)) + suffix
    method = arg.split("(")[0].strip()
    if method in _SAFE_FAKER and hasattr(_fake, method):
        return str(getattr(_fake, method)())
    return m.group(0)


def _valid_value(field: str):
    f = field.lower()
    if "email" in f:
        return _fake.email()
    if "pass" in f:
        return _fake.password(length=10)
    if "phone" in f or "sdt" in f:
        return _fake.phone_number()
    if any(k in f for k in ("qty", "quantity", "so_luong", "amount", "count")):
        return 1
    if any(k in f for k in ("price", "gia", "total")):
        return 100000
    if f.endswith("id") or f == "id":
        return 1
    if "name" in f or "ten" in f:
        return _fake.name()
    if "address" in f or "dia_chi" in f:
        return _fake.address()
    return _fake.word()


def rule_based_data(fields: list[str]) -> list[DataSet]:
    """Bộ dữ liệu EP/BVA tối thiểu không cần AI: 1 hợp lệ + các biến thể lỗi theo từng field."""
    valid = {f: _valid_value(f) for f in fields}
    sets = [DataSet(name="hop_le", values=dict(valid), expected="accept")]
    for f in fields:
        low = f.lower()
        variants: list[tuple[str, object]] = [(f"{f}_rong", "")]
        if "email" in low:
            variants += [(f"{f}_sai_dinh_dang", "abc"), (f"{f}_thieu_ten_mien", "user@"),
                         (f"{f}_qua_dai", resolve_tokens("<len:255:@demo.com>"))]
        elif "pass" in low:
            variants += [(f"{f}_qua_ngan", "12345")]
        elif any(k in low for k in ("qty", "quantity", "so_luong", "amount", "count")):
            variants = [(f"{f}_bang_0", 0), (f"{f}_am", -1)]
            sets.append(DataSet(name=f"{f}_bien_duoi", values={**valid, f: 1}, expected="accept"))
        for name, v in variants:
            sets.append(DataSet(name=name, values={**valid, f: v}, expected="reject"))
    return sets

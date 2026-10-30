# SPDX-License-Identifier: Apache-2.0
"""Agent Expander: sinh kịch bản theo luật từ OpenAPI và dữ liệu thật, không gọi AI.

Dùng khi cần số lượng lớn: AI viết phần lõi cần hiểu nghiệp vụ, Expander phủ phần có quy luật rõ
(giá trị biên, thiếu trường, sai kiểu, tổng tiền từng sản phẩm, biên tồn kho). Không tốn hạn mức và vẫn chạy khi AI lỗi.

Kết quả mong đợi lấy từ ràng buộc trong OpenAPI, dữ liệu thật hoặc mã lỗi nêu trong yêu cầu, không đoán.
Mỗi kịch bản là một hành vi khác nhau: hết hành vi thì dừng, không lặp lại để đủ số.
"""

from __future__ import annotations

import copy
import re
from itertools import zip_longest

import httpx

from ai.http import client as _http
from ai.security_tests import PASSWORD, SENSITIVE, _body_schema, _find, _resolve, _session_steps, _value
from ai.test_generator import is_excluded
from backend.models import Step, TestCase

TECHNIQUE = "rule"
_AUTH_PATH = re.compile(r"login|signin|sign-in", re.I)


def fetch_items(base_url: str, spec: dict | None) -> list[dict]:
    """Dữ liệu thật dạng danh sách có giá (sản phẩm...), đọc từ API GET không tham số."""
    from ai.autopilot import api_base
    if not spec:
        return []
    for path, ops in spec.get("paths", {}).items():
        if "get" not in ops or "{" in path or is_excluded(path):
            continue
        try:
            data = _http.get(api_base(base_url, spec) + path, timeout=5).json()
        except (httpx.HTTPError, ValueError):
            continue
        if isinstance(data, list) and data and isinstance(data[0], dict) and "id" in data[0] and "price" in data[0]:
            return [{**d, "_list_path": path} for d in data]
    return []


def _fields(schema, spec, prefix=()):
    """(đường dẫn, tên, schema, bắt buộc) của mọi trường, gồm trường trong phần tử đầu của mảng."""
    s = _resolve(schema, spec)
    for name, raw in (s.get("properties") or {}).items():
        p = _resolve(raw, spec)
        yield prefix + (name,), name, p, name in (s.get("required") or [])
        if p.get("type") == "array" and p.get("items"):
            yield from _fields(p["items"], spec, prefix + (name, 0))


def _set(body, path, value):
    b = copy.deepcopy(body)
    cur = b
    for k in path[:-1]:
        cur = cur[k]
    cur[path[-1]] = value
    return b


def _drop(body, path):
    b = copy.deepcopy(body)
    cur = b
    for k in path[:-1]:
        cur = cur[k]
    cur.pop(path[-1], None)
    return b


def _exists(body, path) -> bool:
    cur = body
    try:
        for k in path:
            cur = cur[k]
        return True
    except (KeyError, IndexError, TypeError):
        return False


def _text_of(name: str, n: int) -> str:
    """Chuỗi đúng độ dài n, hợp lệ theo loại trường."""
    if "email" in name.lower() and n >= 45:
        return "{{$uuid}}" + "a" * (n - 32 - 12) + "@example.com"
    return "a" * n


def _reject(op: dict) -> dict:
    codes = set((op.get("responses") or {}))
    if "422" in codes:
        return {"status": 422}
    if "400" in codes:
        return {"status": 400}
    return {"status_in": [400, 422]}


def _case(title: str, technique: str, steps: list[Step], priority: str = "medium") -> TestCase:
    return TestCase(id="TC-000", title=title, type="api", priority=priority, category="functional",
                    technique=f"{TECHNIQUE}:{technique}", steps=steps)


def _endpoint_cases(path: str, method: str, op: dict, spec: dict, ids: dict, session: list[Step]) -> list[TestCase]:
    schema = _body_schema(op)
    if not schema:
        return []
    m = method.upper()
    label = f"{m} {path}"
    prefix = list(session) if SENSITIVE.search(path) and not re.search(r"regist|login|signup", path, re.I) else []
    base = _value("body", schema, spec, ids)
    bad = _reject(op)
    ok = {"status_lt": 300}
    # Đăng nhập với tài khoản chưa có sẽ không thành công: chỉ sinh trường hợp bị từ chối
    allow_valid = not _AUTH_PATH.search(path)
    # Form đăng nhập có thể coi email sai định dạng là sai thông tin (401): cả hai đều là từ chối hợp lệ
    bad_format = {"status_in": [400, 401, 403, 422]} if not allow_valid else bad
    out: list[TestCase] = []

    def add(title, technique, body, expect):
        out.append(_case(f"{label}: {title}", technique, prefix + [Step(method=m, path=path, body=body, expect=expect)]))

    for fpath, name, p, required in _fields(schema, spec):
        kind = p.get("type")
        if required:
            add(f"thiếu trường bắt buộc {name}", "missing", _drop(base, fpath), bad)
        if kind == "string":
            lo, hi = p.get("minLength"), p.get("maxLength")
            if lo:
                add(f"{name} rỗng", "empty", _set(base, fpath, ""), bad)
                if lo > 1:
                    add(f"{name} ngắn hơn tối thiểu ({lo - 1} ký tự)", "boundary", _set(base, fpath, _text_of(name, lo - 1)), bad)
                    if allow_valid and "email" not in name.lower():
                        add(f"{name} đúng tối thiểu ({lo} ký tự)", "boundary", _set(base, fpath, _text_of(name, lo)), ok)
            if hi:
                add(f"{name} dài hơn tối đa ({hi + 1} ký tự)", "boundary", _set(base, fpath, _text_of(name, hi + 1)), bad)
                if allow_valid:
                    add(f"{name} đúng tối đa ({hi} ký tự)", "boundary", _set(base, fpath, _text_of(name, hi)), ok)
            add(f"{name} sai kiểu (số)", "type", _set(base, fpath, 12345), bad)
            if "email" in name.lower():
                add(f"{name} thiếu @", "format", _set(base, fpath, "khach.example.com"), bad_format)
                add(f"{name} thiếu tên miền", "format", _set(base, fpath, "khach@example"), bad_format)
        elif kind in ("integer", "number"):
            lo, hi = p.get("minimum"), p.get("maximum")
            if lo is not None:
                add(f"{name} dưới tối thiểu ({lo - 1})", "boundary", _set(base, fpath, lo - 1), bad)
            if hi is not None:
                add(f"{name} trên tối đa ({hi + 1})", "boundary", _set(base, fpath, hi + 1), bad)
            add(f"{name} sai kiểu (chữ)", "type", _set(base, fpath, "khong-phai-so"), bad)
        elif kind == "array":
            if p.get("minItems"):
                add(f"{name} rỗng", "empty", _set(base, fpath, []), bad)
    return out


def _order_endpoint(spec: dict):
    """Endpoint tạo đơn: body có mảng phần tử gồm một mã (id) và một số lượng (integer)."""
    for path, ops in spec.get("paths", {}).items():
        if "post" not in ops or is_excluded(path) or not _body_schema(ops["post"]):
            continue
        for fpath, _, p, _ in _fields(_body_schema(ops["post"]), spec):
            if p.get("type") != "array" or not p.get("items"):
                continue
            item = _resolve(p["items"], spec).get("properties") or {}
            id_key = next((k for k in item if k.lower().endswith("id")), None)
            qty_key = next((k for k, v in item.items() if _resolve(v, spec).get("type") == "integer"), None)
            if id_key and qty_key:
                return path, fpath, id_key, qty_key, _resolve(item[qty_key], spec).get("maximum")
    return None


def _business_cases(spec: dict, items: list[dict], text: str, session: list[Step]) -> list[TestCase]:
    found = _order_endpoint(spec)
    if not found or not items:
        return []
    path, fpath, id_key, qty_key, qty_max = found
    wants_total = bool(re.search(r"total|tổng", text, re.I))
    over = {"status": 409} if re.search(r"\b409\b", text) else {"status_in": [409, 422]}
    base = _value("body", _body_schema(spec["paths"][path]["post"]), spec, {"id": items[0]["id"]})
    lookup = next(((p, re.search(r"\{(\w+)\}", p).group(1)) for p, o in spec["paths"].items()
                   if "get" in o and "{" in p and SENSITIVE.search(p) and not is_excluded(p)), None)

    def order(lines, expect, save=None):
        body = _set(base, fpath, [{id_key: i, qty_key: q} for i, q in lines])
        return Step(method="POST", path=path, body=body, expect=expect, save=save)

    out: list[TestCase] = []
    for it in items:
        pid, name, price = it["id"], it.get("name") or it["id"], it["price"]
        stock = it.get("stock")
        for q in (1, 2):
            if stock is not None and q > stock:
                continue
            exp: dict = {"status_lt": 300}
            if wants_total:
                exp["json_contains"] = {"total": price * q}
            out.append(_case(f"Đặt {q} {name}: tổng tiền bằng đơn giá nhân số lượng", "business", session + [order([(pid, q)], exp)], "high"))
        if stock is not None and (qty_max is None or stock <= qty_max):
            out.append(_case(f"Đặt đúng bằng tồn kho {name} ({stock}) được chấp nhận", "stock", session + [order([(pid, stock)], {"status_lt": 300})]))
        if stock is not None and (qty_max is None or stock + 1 <= qty_max):
            out.append(_case(f"Đặt vượt tồn kho {name} ({stock + 1}) bị từ chối", "stock", session + [order([(pid, stock + 1)], over)], "high"))
        if stock is not None and it.get("_list_path"):
            out.append(_case(f"Đặt {name} xong tồn kho giảm đúng", "state", session + [
                order([(pid, 1)], {"status_lt": 300}),
                Step(method="GET", path=it["_list_path"], expect={"status": 200, "json_contains": [{"id": pid, "stock": stock - 1}]})], "high"))
        if lookup:
            var = lookup[1]
            exp = {"status": 200, "json_contains": {"total": price}} if wants_total else {"status": 200}
            out.append(_case(f"Đặt {name} rồi tra cứu lại đơn", "state", session + [
                order([(pid, 1)], {"status_lt": 300}, {var: var}),
                Step(method="GET", path=lookup[0].replace("{" + var + "}", "{{" + var + "}}"), expect=exp)]))
    for a, b in zip(items, items[1:]):
        exp = {"status_lt": 300}
        if wants_total:
            exp["json_contains"] = {"total": a["price"] + b["price"]}
        out.append(_case(f"Đặt cùng lúc {a.get('name', a['id'])} và {b.get('name', b['id'])}: tổng tiền cộng đúng", "business",
                         session + [order([(a["id"], 1), (b["id"], 1)], exp)]))
    if re.search(r"không tồn tại|not found|\b404\b", text, re.I):
        out.append(_case("Đặt sản phẩm không tồn tại bị từ chối", "negative", session + [order([("khong-ton-tai", 1)], {"status": 404})]))
    if re.search(r"\b401\b", text):
        out.append(_case("Đặt hàng khi chưa đăng nhập bị từ chối", "auth", [order([(items[0]["id"], 1)], {"status": 401})], "high"))
    return out


def _auth_cases(spec: dict, session: list[Step]) -> list[TestCase]:
    login, logout = _find(spec, r"login|signin"), _find(spec, r"logout|signout")
    me = next((p for p, o in spec.get("paths", {}).items() if "get" in o and re.search(r"/me\b", p) and not is_excluded(p)), None)
    if not (login and session):
        return []
    creds = {k: v for k, v in session[0].body.items() if re.search("email|user|pass", k, re.I)}
    wrong = {k: ("sai-mat-khau-demo" if "pass" in k.lower() else v) for k, v in creds.items()}
    denied = {"status_in": [400, 401, 403]}
    out = [_case("Đăng ký rồi đăng nhập đúng thành công", "auth", [session[0], Step(method="POST", path=login, body=creds, expect={"status_lt": 300})], "high"),
           _case("Đăng nhập sai mật khẩu bị từ chối", "auth", [session[0], Step(method="POST", path=login, body=wrong, expect=denied)], "high"),
           _case("Đăng nhập bằng tài khoản chưa đăng ký bị từ chối", "auth", [Step(method="POST", path=login, body=creds, expect=denied)])]
    reg = session[0].path
    out.append(_case("Đăng ký trùng email bị từ chối", "auth", [
        Step(method="POST", path=reg, body={**session[0].body, "email": "{{dup}}"}, expect={"status_lt": 300}),
        Step(method="POST", path=reg, body={**session[0].body, "email": "{{dup}}"}, expect={"status_in": [400, 409, 422]})]))
    out[-1].data_sets = [_dup_set()]
    if me:
        out.append(_case("Chưa đăng nhập không xem được tài khoản", "auth", [Step(method="GET", path=me, expect={"status_in": [401, 403]})]))
        out.append(_case("Sau khi đăng ký xem được tài khoản", "auth", [session[0], Step(method="GET", path=me, expect={"status": 200})]))
        if logout:
            out.append(_case("Đăng xuất xong không xem được tài khoản", "auth", [
                session[0], Step(method="POST", path=logout, expect={"status_lt": 300}),
                Step(method="GET", path=me, expect={"status_in": [401, 403]})], "high"))
    return out


def _dup_set():
    from backend.models import DataSet
    return DataSet(name="email_trung", values={"dup": "{{$email}}"})


def _list_cases(items: list[dict]) -> list[TestCase]:
    out = []
    for it in items:
        expect = {k: it[k] for k in ("id", "price") if k in it}
        out.append(_case(f"Danh sách có {it.get('name', it['id'])} với giá đúng", "data", [
            Step(method="GET", path=it["_list_path"], expect={"status": 200, "json_contains": [expect]})], "low"))
    return out


def build_cases(spec: dict | None, text: str, items: list[dict] | None = None, limit: int = 150,
                sample_ids: dict | None = None) -> list[TestCase]:
    """Sinh tối đa limit kịch bản, xen kẽ các nhóm để số lượng ít vẫn đa dạng."""
    if not spec:
        return []
    items = items or []
    ids = sample_ids or ({"id": items[0]["id"]} if items else {})
    session = _session_steps(spec, ids)
    groups = [_business_cases(spec, items, text, session), _auth_cases(spec, session)]
    for path, ops in spec.get("paths", {}).items():
        if is_excluded(path) or re.search(r"logout|signout", path, re.I):
            continue
        for method, op in ops.items():
            if method in ("post", "put", "patch"):
                groups.append(_endpoint_cases(path, method, op, spec, ids, session))
    groups.append(_list_cases(items))
    merged, seen = [], set()
    for row in zip_longest(*groups):
        for tc in row:
            if tc is not None and tc.title not in seen:
                seen.add(tc.title)
                merged.append(tc)
    return merged[:limit]

# SPDX-License-Identifier: Apache-2.0
"""Runner API tối giản để thử test case do AI sinh (chạy + AI phân loại lỗi).

Đây là bản tham khảo cho Runner chính thức (backend/runner/, phần của C):
cùng quy ước thay {{biến}}, kiểm tra status/json_contains và lưu biến bằng "save".
"""

from __future__ import annotations

import re
import statistics
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

import httpx

from ai.http import client as _http, hooks
from backend.models import TestCase

_PH = re.compile(r"\{\{\s*([\w$]+)\s*\}\}")


def substitute(value, variables: dict):
    """Thay {{x}}. Nếu cả chuỗi chỉ là "{{x}}" thì giữ nguyên kiểu (số vẫn là số)."""
    if isinstance(value, str):
        m = _PH.fullmatch(value.strip())
        if m and m.group(1) in variables:
            return variables[m.group(1)]
        return _PH.sub(lambda m: str(variables.get(m.group(1), m.group(0))), value)
    if isinstance(value, dict):
        return {k: substitute(v, variables) for k, v in value.items()}
    if isinstance(value, list):
        return [substitute(v, variables) for v in value]
    return value


def json_contains(expected, actual) -> bool:
    """expected là tập con của actual (dict lồng nhau, list: mỗi phần tử phải khớp một phần tử)."""
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(k in actual and json_contains(v, actual[k])
                                                for k, v in expected.items())
    if isinstance(expected, list):
        return isinstance(actual, list) and all(any(json_contains(e, a) for a in actual) for e in expected)
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        try:
            return float(expected) == float(actual)
        except (TypeError, ValueError):
            return False
    return expected == actual


def dig(data, path: str):
    # AI hay viết items[0].id: hiểu như items.0.id
    for key in re.sub(r"\[(\d+)\]", r".\1", path).lstrip(".").split("."):
        data = data[int(key)] if isinstance(data, list) else data[key]
    return data


class _Prefixed:
    """Phiên HTTP cho một lượt chạy: cookie riêng (đăng nhập ở bước trước dùng cho bước sau,
    không lẫn sang kịch bản khác) nhưng dùng chung kết nối của ai.http — không tốn ~0,7s tạo SSL."""

    def __init__(self, base_url: str, timeout: float):
        self.base, self.timeout = base_url.rstrip("/"), timeout
        self.session = httpx.Client(transport=_http._transport, timeout=timeout, follow_redirects=True,
                                    event_hooks=hooks)

    def request(self, method: str, path: str, **kw):
        return self.session.request(method, self.base + path, **kw)


USER_MARK, PASS_MARK = "__USERNAME__", "__PASSWORD__"


class MissingCredentials(Exception):
    """Kịch bản cần tài khoản thử nghiệm nhưng lượt chạy này không có."""


def run_variables(ds, credentials: dict | None = None) -> dict:
    """Biến cho một lượt chạy: biến sinh lúc chạy + giá trị data set (giá trị data set cũng được
    thay biến, vd. {"email": "{{$email}}"} → email duy nhất của lượt này).
    credentials: tài khoản thật thay cho dấu __USERNAME__/__PASSWORD__, chỉ tồn tại trong lượt chạy."""
    rt = runtime_vars()
    out = {**rt, **{k: substitute(v, rt) for k, v in (ds.values.items() if ds else [])}}
    for k, v in out.items():
        if isinstance(v, str) and v in (USER_MARK, PASS_MARK):
            if not credentials:
                raise MissingCredentials(k)
            out[k] = credentials["username"] if v == USER_MARK else credentials["password"]
    return out


def redact(value):
    """Che mật khẩu/token trong kết quả trả về giao diện và báo cáo."""
    if isinstance(value, dict):
        return {k: ("••••••" if re.search(r"pass|pwd|token|secret", k, re.I) and isinstance(v, str) and v else redact(v))
                for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def check_expect(expect: dict, r: httpx.Response, resp, elapsed_ms: int) -> str | None:
    """Kiểm tra kết quả một bước API. Trả về thông báo lỗi hoặc None nếu đạt.
    Ngoài status/json_contains còn có: status_in, status_lt, max_ms, headers, not_contains,
    cookie_flags, not_reflected_html."""
    if expect.get("status") and r.status_code != int(expect["status"]):
        return f"expected status {expect['status']}, got {r.status_code}"
    if expect.get("status_in") and r.status_code not in expect["status_in"]:
        return f"expected status in {expect['status_in']}, got {r.status_code}"
    if expect.get("status_lt") and r.status_code >= int(expect["status_lt"]):
        return f"expected status < {expect['status_lt']}, got {r.status_code}"
    if expect.get("json_contains") and not json_contains(expect["json_contains"], resp):
        return f"response không chứa {expect['json_contains']}"
    if expect.get("max_ms") and elapsed_ms > int(expect["max_ms"]):
        return f"expected response within {expect['max_ms']}ms, took {elapsed_ms}ms"
    missing = [h for h in expect.get("headers") or [] if h.lower() not in r.headers]
    if missing:
        return f"thiếu header bảo mật: {', '.join(missing)}"
    leaked = [t for t in expect.get("not_contains") or [] if t.lower() in r.text.lower()]
    if leaked:
        return f"response để lộ thông tin nội bộ: {', '.join(leaked)}"
    if expect.get("cookie_flags"):
        cookie = r.headers.get("set-cookie", "").lower()
        if not cookie:
            return "response không đặt cookie phiên"
        absent = [f for f in expect["cookie_flags"] if f.lower() not in cookie]
        if absent:
            return f"cookie phiên thiếu thuộc tính: {', '.join(absent)}"
    payload = expect.get("not_reflected_html")
    if payload and "text/html" in r.headers.get("content-type", "") and payload in r.text:
        return "dữ liệu chèn vào được phản chiếu nguyên dạng trong HTML (XSS)"
    return None


MAX_REQUESTS, MAX_CONCURRENCY = 100, 10
REMOTE_REQUESTS, REMOTE_CONCURRENCY = 20, 3    # website bên ngoài: chỉ đo nhẹ, không phải kiểm thử tải


def run_perf(step, base_url: str, path: str, body, *, local: bool, timeout: float = 10.0) -> tuple[dict, str | None]:
    """Gửi nhiều request (có giới hạn) rồi tính p50/p95/tỉ lệ lỗi. Trả về (số đo, lỗi hoặc None).
    Đây là phép đo nhanh để phát hiện suy giảm, không thay thế công cụ kiểm thử tải chuyên dụng."""
    cfg = step.perf or {}
    n = max(1, min(int(cfg.get("requests", 20)), MAX_REQUESTS if local else REMOTE_REQUESTS))
    workers = max(1, min(int(cfg.get("concurrency", 5)), MAX_CONCURRENCY if local else REMOTE_CONCURRENCY))

    def one(_):
        t = time.perf_counter()
        try:
            r = _http.request(step.method or "GET", base_url.rstrip("/") + path, json=body, timeout=timeout)
            return (time.perf_counter() - t) * 1000, r.status_code
        except httpx.HTTPError:
            return (time.perf_counter() - t) * 1000, 0

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        samples = list(pool.map(one, range(n)))
    wall = time.perf_counter() - t0
    times = sorted(t for t, _ in samples)
    codes = [c for _, c in samples]
    errors = sum(1 for c in codes if c == 0 or c >= 500)
    p95 = statistics.quantiles(times, n=20)[18] if len(times) >= 2 else times[0]
    m = {"requests": n, "concurrency": workers, "p50_ms": round(statistics.median(times)), "p95_ms": round(p95),
         "max_ms": round(times[-1]), "rps": round(n / wall, 1) if wall else None,
         "error_rate": round(errors / n, 3), "status_codes": sorted(set(codes))}
    if cfg.get("min_blocked") is not None:      # kiểm tra giới hạn số lần thử (đăng nhập sai liên tiếp)
        blocked = sum(1 for c in codes if c in (423, 429))
        m["blocked"] = blocked
        if blocked < int(cfg["min_blocked"]):
            return m, f"gửi {n} lần liên tiếp nhưng không bị giới hạn (không có HTTP 429/423)"
        return m, None
    if cfg.get("p95_ms") and m["p95_ms"] > int(cfg["p95_ms"]):
        return m, f"p95 {m['p95_ms']}ms vượt ngưỡng {cfg['p95_ms']}ms"
    if m["error_rate"] > float(cfg.get("max_error_rate", 0)):
        return m, f"tỉ lệ lỗi {m['error_rate']:.1%} vượt ngưỡng {float(cfg.get('max_error_rate', 0)):.1%}"
    return m, None


def runtime_vars() -> dict:
    """Biến sinh lúc chạy, khác nhau mỗi lượt: {{$email}}, {{$uuid}}, {{$ts}}, {{$name}}."""
    u = uuid.uuid4().hex
    return {"$uuid": u, "$ts": str(int(time.time() * 1000)), "$email": f"tp_{u[:10]}@example.com",
            "$name": f"TestPilot {u[:6]}"}


def run_api_test(tc: TestCase, base_url: str, *, before_each: Callable[[], None] | None = None,
                 timeout: float = 10.0, credentials: dict | None = None, local: bool = True) -> list[dict]:
    """Chạy test case API với từng data set. Trả về mỗi data set một kết quả:
    {data_set, expected, status: passed|failed, error_msg, duration_ms, step, request,
     expected_status, actual_status, response_body}."""
    results = []
    for ds in tc.data_sets or [None]:
        res = _run_data_set(tc, ds, base_url, before_each, timeout, credentials, local)
        if res.get("connection_error"):
            # Sự cố đường truyền không phải kết quả kiểm thử: chạy lại cả lượt một lần từ trạng thái sạch
            res = {**_run_data_set(tc, ds, base_url, before_each, timeout, credentials, local), "retried": True}
        results.append(res)
    return results


def _run_data_set(tc: TestCase, ds, base_url: str, before_each, timeout: float, credentials, local: bool) -> dict:
    client = _Prefixed(base_url, timeout)          # phiên mới cho mỗi lượt
    res: dict = {"data_set": ds.name if ds else "-", "expected": ds.expected if ds else "accept",
                 "status": "passed", "error_msg": ""}
    try:
        if before_each:
            before_each()
    except httpx.HTTPError as e:
        res.update(status="failed", connection_error=True, duration_ms=0, error_msg=f"lỗi kết nối khi đặt lại dữ liệu: {e}")
        return res
    try:
        variables = run_variables(ds, credentials)
    except MissingCredentials:
        res.update(status="failed", duration_ms=0, needs_credentials=True,
                   error_msg="Kịch bản cần tài khoản thử nghiệm: nhập tài khoản rồi thực thi lại.")
        return res
    t0 = time.perf_counter()
    for i, step in enumerate(tc.steps):
        path = substitute(step.path or "", variables)
        body = substitute(step.body, variables)
        expect = substitute(step.expect, variables) or {}
        res.update(step=i, request={"method": step.method, "path": path, "body": redact(body)})
        if step.perf:
            metrics, err = run_perf(step, base_url, path, body, local=local, timeout=timeout)
            res["perf"] = metrics
            if err:
                res.update(status="failed", error_msg=err)
                break
            continue
        t_step = time.perf_counter()
        try:
            r = client.request(step.method or "GET", path, json=body, headers=step.headers)
        except httpx.HTTPError as e:
            res.update(status="failed", connection_error=True, error_msg=f"lỗi kết nối: {e}")
            break
        try:
            resp = r.json()
        except ValueError:
            resp = r.text[:2000]
        elapsed = int((time.perf_counter() - t_step) * 1000)
        res.update(expected_status=expect.get("status") if isinstance(expect, dict) else None,
                   actual_status=r.status_code, response_body=redact(resp), step_ms=elapsed)
        if isinstance(expect, dict):
            err = check_expect(expect, r, resp, elapsed)
            if err:
                res.update(status="failed", error_msg=err)
                break
        for var, p in (step.save or {}).items():
            try:
                variables[var] = dig(resp, p)
            except (KeyError, IndexError, TypeError, ValueError):
                res.update(status="failed", error_msg=f"không lấy được '{p}' từ response để lưu vào {var}")
                break
        if res["status"] == "failed":
            break
    res["duration_ms"] = int((time.perf_counter() - t0) * 1000)
    return res

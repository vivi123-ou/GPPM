# SPDX-License-Identifier: Apache-2.0
"""Runner API tối giản để thử test case do AI sinh (chạy + AI phân loại lỗi).

Đây là bản tham khảo cho Runner chính thức (backend/runner/, phần của C):
cùng quy ước thay {{biến}}, kiểm tra status/json_contains và lưu biến bằng "save".
"""

from __future__ import annotations

import re
import time
from contextlib import nullcontext
from typing import Callable

import httpx

from ai.http import client as _http
from backend.models import TestCase

_PH = re.compile(r"\{\{\s*(\w+)\s*\}\}")


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
    for key in path.split("."):
        data = data[int(key)] if isinstance(data, list) else data[key]
    return data


class _Prefixed:
    """Gọi qua client dùng chung (ai.http) với URL gốc cố định — không tạo client mới mỗi kịch bản."""

    def __init__(self, base_url: str, timeout: float):
        self.base, self.timeout = base_url.rstrip("/"), timeout

    def request(self, method: str, path: str, **kw):
        return _http.request(method, self.base + path, timeout=self.timeout, **kw)


def run_api_test(tc: TestCase, base_url: str, *, before_each: Callable[[], None] | None = None,
                 timeout: float = 10.0) -> list[dict]:
    """Chạy test case API với từng data set. Trả về mỗi data set một kết quả:
    {data_set, expected, status: passed|failed, error_msg, duration_ms, step, request,
     expected_status, actual_status, response_body}."""
    results = []
    data_sets = tc.data_sets or [None]
    with nullcontext(_Prefixed(base_url, timeout)) as client:
        for ds in data_sets:
            if before_each:
                before_each()
            variables = dict(ds.values) if ds else {}
            res: dict = {"data_set": ds.name if ds else "-", "expected": ds.expected if ds else "accept",
                         "status": "passed", "error_msg": ""}
            t0 = time.perf_counter()
            for i, step in enumerate(tc.steps):
                path = substitute(step.path or "", variables)
                body = substitute(step.body, variables)
                expect = substitute(step.expect, variables) or {}
                res.update(step=i, request={"method": step.method, "path": path, "body": body})
                try:
                    r = client.request(step.method or "GET", path, json=body, headers=step.headers)
                except httpx.HTTPError as e:
                    res.update(status="failed", error_msg=f"lỗi kết nối: {e}")
                    break
                try:
                    resp = r.json()
                except ValueError:
                    resp = r.text[:2000]
                res.update(expected_status=expect.get("status") if isinstance(expect, dict) else None,
                           actual_status=r.status_code, response_body=resp)
                if isinstance(expect, dict):
                    if expect.get("status") and r.status_code != int(expect["status"]):
                        res.update(status="failed",
                                   error_msg=f"expected status {expect['status']}, got {r.status_code}")
                        break
                    if expect.get("json_contains") and not json_contains(expect["json_contains"], resp):
                        res.update(status="failed",
                                   error_msg=f"response không chứa {expect['json_contains']}")
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
            results.append(res)
    return results

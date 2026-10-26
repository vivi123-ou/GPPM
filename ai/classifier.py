# SPDX-License-Identifier: Apache-2.0
"""Phân loại test fail: app_bug (lỗi thật của app) / test_broken (test hỏng) / flaky.

Chạy heuristic trước (nhanh, không tốn token) rồi cho LLM quyết định cuối cùng
kèm giải thích. Nếu LLM không gọi được thì trả về kết quả heuristic.
"""

from __future__ import annotations

import json
import re

from ai import prompts
from ai.llm_provider import LLMProvider, get_provider
from backend.models import TestCase

VERDICTS = ("app_bug", "test_broken", "flaky")
# Dấu hiệu LLM viết code thay cho dữ liệu: "a".repeat(300), "x" * 101, new Array(…)
CODE_IN_DATA = re.compile(r"\.repeat\(|new Array\(|\\\"\s*\*\s*\d+|\"\s*\+\s*\"")

_LOCATOR_HINTS = ("waiting for locator", "waiting for selector", "strict mode violation",
                  "element is not attached", "no element", "not found", "resolved to 0 elements",
                  "locator", "getbytestid", "getbyrole")
_FLAKY_HINTS = ("timeout", "timed out", "econnreset", "econnrefused", "connection reset",
                "connection refused", "network", "503", "502", "504", "socket", "net::err")
_ASSERT_HINTS = ("expected", "assert", "status", "mismatch", "khác", "mong đợi")


def heuristic(test_case: TestCase | dict, result: dict, api_paths: list[str] | None = None) -> dict:
    """Đoán nhanh dựa trên thông báo lỗi và lịch sử chạy."""
    err = _error_text(result).lower()
    tc_type = test_case.type if isinstance(test_case, TestCase) else test_case.get("type")

    path = ((result.get("request") or {}).get("path") or "").split("?")[0]
    if api_paths and path and result.get("actual_status") in (404, 405) \
            and not any(_path_match(p, path) for p in api_paths):
        return _v("test_broken", 0.85, f"Test gọi {path} nhưng API này không có trong OpenAPI của hệ thống.")

    if result.get("passed_on_retry") or result.get("retry_status") == "passed":
        return _v("flaky", 0.85, "Test pass khi chạy lại → kết quả không ổn định.")
    history = result.get("history") or []
    if len(set(history[-5:])) > 1 and "passed" in history and "failed" in history:
        return _v("flaky", 0.6, "Lịch sử chạy gần đây lúc pass lúc fail.")
    tc_text = (test_case.model_dump_json() if isinstance(test_case, TestCase)
               else json.dumps(test_case, ensure_ascii=False, default=str))
    if CODE_IN_DATA.search(tc_text):
        return _v("test_broken", 0.85, "Dữ liệu kiểm thử chứa biểu thức code (vd. .repeat()) thay vì giá trị thật, "
                                       "nên request gửi đi không đúng như kịch bản mô tả.")
    if "để lưu vào" in err:
        return _v("test_broken", 0.75, "Test đọc sai trường trong response (bước 'save'); "
                                       "API vẫn trả kết quả nhưng tên trường khác với test giả định.")
    if tc_type == "ui" and any(h in err for h in _LOCATOR_HINTS):
        return _v("test_broken", 0.7, "Không tìm thấy phần tử theo locator → có thể giao diện đã đổi.")
    if any(h in err for h in _FLAKY_HINTS) and not any(h in err for h in ("expected", "assert")):
        return _v("flaky", 0.55, "Lỗi mạng/timeout, có thể do môi trường.")
    if result.get("actual_status") is not None or any(h in err for h in _ASSERT_HINTS):
        return _v("app_bug", 0.6, "Kết quả thực tế khác kết quả mong đợi.")
    return _v("app_bug", 0.3, "Chưa đủ dữ kiện; mặc định nghi lỗi ứng dụng.")


def classify_failure(test_case: TestCase | dict, result: dict, requirement_text: str = "",
                     provider: LLMProvider | None = None, api_paths: list[str] | None = None,
                     context: str = "") -> dict:
    """result: dict tuỳ ý từ Runner, nên có error_msg, step lỗi, expected/actual,
    response body, history... Càng nhiều dữ kiện AI giải thích càng đúng.
    api_paths: các path có thật (từ OpenAPI) để nhận ra test gọi sai API.
    context: dữ liệu thật của hệ thống + ràng buộc OpenAPI để AI kiểm lại kỳ vọng của test."""
    hint = heuristic(test_case, result, api_paths)
    tc_json = (test_case.model_dump_json(exclude_none=True) if isinstance(test_case, TestCase)
               else json.dumps(test_case, ensure_ascii=False, default=str))
    if requirement_text:
        tc_json = f"Requirement: {requirement_text}\n{tc_json}"
    if api_paths:
        tc_json += "\n\nAPI paths that really exist in the system: " + ", ".join(api_paths)
    try:
        llm = provider or get_provider()
        data = llm.complete_json(prompts.CLASSIFY_SYSTEM, prompts.CLASSIFY_USER.format(
            test_case=tc_json[:6000], result=_compact(result), hint=json.dumps(hint, ensure_ascii=False),
            context=("System context (real data and API constraints):\n" + context[:5000]) if context else ""))
        if not isinstance(data, dict):
            raise ValueError("không phải object")
        verdict = str(data.get("verdict", "")).lower().strip()
        if verdict not in VERDICTS:
            raise ValueError(f"verdict lạ: {verdict}")
        return {"verdict": verdict,
                "confidence": _float(data.get("confidence"), 0.7),
                "explanation": str(data.get("explanation") or hint["explanation"]),
                "suggested_fix": str(data.get("suggested_fix") or ""),
                "source": "ai"}
    except Exception as e:
        return {**hint, "source": "heuristic", "ai_error": str(e)[:200]}


def _path_match(template: str, path: str) -> bool:
    """/api/orders/{id} khớp /api/orders/5."""
    t, p = template.strip("/").split("/"), path.strip("/").split("/")
    return len(t) == len(p) and all(a == b or (a.startswith("{") and a.endswith("}")) for a, b in zip(t, p))


def _v(verdict, conf, why):
    return {"verdict": verdict, "confidence": conf, "explanation": why, "suggested_fix": ""}


def _error_text(result: dict) -> str:
    parts = [str(result.get(k, "")) for k in ("error_msg", "error", "message", "detail")]
    for s in result.get("steps") or result.get("step_results") or []:
        if isinstance(s, dict) and s.get("status") not in ("passed", "pass", "ok"):
            parts.append(str(s.get("detail") or s.get("error") or ""))
    return " ".join(p for p in parts if p)


def _compact(result: dict, limit: int = 6000) -> str:
    # Bỏ ảnh base64 / đường dẫn ảnh dài — vô ích với LLM
    def strip(v):
        if isinstance(v, dict):
            return {k: strip(x) for k, x in v.items() if "screenshot" not in k}
        if isinstance(v, list):
            return [strip(x) for x in v[:30]]
        if isinstance(v, str) and len(v) > 1500:
            return v[:1500] + "…"
        return v
    return json.dumps(strip(result), ensure_ascii=False, default=str)[:limit]


def _float(v, default):
    try:
        return max(0.0, min(1.0, float(v)))
    except (TypeError, ValueError):
        return default

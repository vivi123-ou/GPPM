# SPDX-License-Identifier: Apache-2.0
"""Agent Verifier: chạy thử kịch bản ngay sau khi sinh, vì nhiều lỗi chỉ lộ ra khi chạy thật
(ví dụ đọc một trường API không trả về), luật đọc JSON không thấy được.

Kết quả mỗi kịch bản: passed | app_bug | test_broken | flaky | skipped.
Không đạt thì chạy lại một lần để nhận biết không ổn định, rồi Triage phân loại.
Chạy thử không bật self-healing: locator sai ở bước này là lỗi của kịch bản vừa sinh.
"""

from __future__ import annotations

from ai.classifier import classify_failures, heuristic
from ai.quick_runner import run_api_test
from backend.models import TestCase


def run_cases(cases: list[TestCase], url: str, base: str, *, before_each=None, credentials=None, local: bool = True) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    ui = [c for c in cases if c.type == "ui"]
    if ui:
        from ai.ui_runner import run_ui_tests
        if before_each:
            before_each()
        out.update(run_ui_tests(ui, url, heal=False, credentials=credentials))
    for c in cases:
        if c.type != "ui":
            out[c.id] = run_api_test(c, base, before_each=before_each, credentials=credentials, local=local)
    return out


def _failed(results: list[dict]) -> dict | None:
    return next((r for r in results if r["status"] == "failed"), None)


def verify(cases: list[TestCase], url: str, base: str, *, before_each=None, credentials=None, local: bool = True,
           provider=None, api_paths=None, context: str = "") -> dict[str, dict]:
    if not cases:
        return {}
    first = run_cases(cases, url, base, before_each=before_each, credentials=credentials, local=local)
    status: dict[str, dict] = {}
    failing = []
    for c in cases:
        bad = _failed(first.get(c.id, []))
        if bad is None:
            status[c.id] = {"status": "passed"}
        elif bad.get("needs_credentials"):
            status[c.id] = {"status": "skipped", "detail": "chưa có tài khoản thử nghiệm"}
        else:
            failing.append(c)
    if not failing:
        return status

    second = run_cases(failing, url, base, before_each=before_each, credentials=credentials, local=local)
    to_classify = []
    for c in failing:
        if _failed(second.get(c.id, [])) is None:
            status[c.id] = {"status": "flaky", "detail": _failed(first[c.id]).get("error_msg", "")}
        elif (c.technique or "").startswith("rule:"):
            # Kịch bản sinh theo luật: không tốn AI để phân loại; kết luận chỉ là nghi vấn, người xem lại
            bad = _failed(second[c.id])
            h = heuristic(c, bad, api_paths)
            status[c.id] = {"status": h["verdict"], "detail": f"Nghi vấn cần xác nhận: {bad.get('error_msg', '')}"[:300]}
        else:
            bad = _failed(second[c.id])
            to_classify.append((c, {"test_case_id": c.id, "title": c.title, "type": c.type, "category": c.category,
                                    **{k: v for k, v in bad.items() if k != "screenshot"}}))
    verdicts = classify_failures(to_classify, api_paths, context, provider=provider)
    for (c, item), v in zip(to_classify, verdicts):
        verdict = v.get("verdict")
        status[c.id] = {"status": verdict if verdict in ("app_bug", "test_broken", "flaky") else "test_broken",
                        "detail": (v.get("explanation") or item.get("error_msg") or "")[:300],
                        "evidence": {"error": item.get("error_msg"), "request": item.get("request"),
                                     "expected_status": item.get("expected_status"), "actual_status": item.get("actual_status"),
                                     "response": str(item.get("response_body"))[:800], "steps": item.get("steps"),
                                     "triage": v.get("explanation"), "suggested_fix": v.get("suggested_fix")}}
    return status

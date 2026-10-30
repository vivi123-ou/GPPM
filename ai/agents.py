# SPDX-License-Identifier: Apache-2.0
"""Điều phối nhiều agent cho việc sinh kịch bản. Mỗi agent có một việc rõ ràng và được ghi vết.

  Lead        đọc yêu cầu, lập kế hoạch, giao việc, quyết định vòng tiếp theo
  Context     đọc OpenAPI và dữ liệu thật của hệ thống
  Writer      viết kịch bản chức năng (LLM + skill + bài học)
  Security    dò theo OpenAPI (không cần AI) + lỗi nghiệp vụ (LLM)
  Performance đo hiệu năng (không cần AI)
  Reviewer    chấm điểm bằng luật + đối chiếu yêu cầu bằng LLM
  Fixer       sửa kịch bản bị chê hoặc chạy thử lỗi
  Verifier    chạy thử thật trên hệ thống, Triage xác định lỗi do kịch bản hay do ứng dụng

Kế hoạch do LLM đề xuất nhưng code kiểm tra và giới hạn: Lead chỉ giao việc trong phạm vi người dùng chọn,
không tự bật kiểm thử bảo mật/hiệu năng, số vòng sửa có trần. Một agent lỗi không làm hỏng cả lượt.

Fixer không được làm yếu kịch bản để cho "đạt": bản sửa bị loại nếu giảm số kiểm tra, hoặc đổi kết quả
mong đợi mà yêu cầu đã nêu rõ. Sửa theo kết quả chạy thử chỉ được giữ khi chạy lại đạt.
"""

from __future__ import annotations

import json
import re
import time
from urllib.parse import urlparse

from ai import expander, prompts, review, security_tests, skills
from ai.json_utils import unwrap_list
from ai.llm_provider import LLMProvider, get_provider
from ai.test_generator import _prefix_for, _validate_all, generate_test_cases, is_excluded, summarize_openapi
from backend.models import TestCase

CATALOG = [
    {"id": "lead", "name": "Lead", "uses_llm": True, "job": "Đọc yêu cầu, tách tiêu chí, lập kế hoạch và giao việc; thiếu tiêu chí thì giao viết thêm; quyết định có sửa tiếp không."},
    {"id": "context", "name": "Context", "uses_llm": False, "job": "Đọc OpenAPI và dữ liệu thật của hệ thống đích."},
    {"id": "explorer", "name": "Explorer", "uses_llm": True, "job": "Autopilot: duyệt website bằng trình duyệt, lập bản đồ trang, đề xuất luồng UI."},
    {"id": "writer", "name": "Writer", "uses_llm": True, "job": "Viết kịch bản chức năng từ yêu cầu, dùng skill và bài học đã duyệt."},
    {"id": "expander", "name": "Expander", "uses_llm": False, "job": "Khi cần số lượng lớn: sinh kịch bản từ OpenAPI và dữ liệu thật (giá trị biên, thiếu trường, tổng tiền, tồn kho), không tốn hạn mức AI."},
    {"id": "security", "name": "Security", "uses_llm": True, "job": "Dò điểm yếu theo OWASP từ OpenAPI (không cần AI) và lỗi logic nghiệp vụ (AI)."},
    {"id": "performance", "name": "Performance", "uses_llm": False, "job": "Đo p50, p95 và tỉ lệ lỗi ở tải nhẹ để phát hiện suy giảm."},
    {"id": "reviewer", "name": "Reviewer", "uses_llm": True, "job": "Chấm điểm kịch bản bằng 17 luật tự động, đối chiếu tiêu chí chấp nhận bằng AI."},
    {"id": "verifier", "name": "Verifier", "uses_llm": False, "job": "Chạy thử kịch bản trên hệ thống thật, chạy lại để nhận biết không ổn định, chuyển lỗi cho Triage."},
    {"id": "fixer", "name": "Fixer", "uses_llm": True, "job": "Sửa kịch bản theo nhận xét và lỗi chạy thử; không được giảm kiểm tra; chỉ giữ khi chạy lại đạt."},
    {"id": "triage", "name": "Triage", "uses_llm": True, "job": "Phân loại kết quả không đạt: lỗi ứng dụng, lỗi kịch bản hay không ổn định."},
    {"id": "healer", "name": "Healer", "uses_llm": True, "job": "Self-healing: đề xuất locator thay thế từ DOM mới, chạy thử trước khi đề xuất."},
    {"id": "learner", "name": "Learner", "uses_llm": True, "job": "Rút bài học từ lỗi kịch bản và lý do từ chối; người duyệt mới có hiệu lực."},
]

MAX_REPAIR_ROUNDS = 2
ECONOMY_CORE = 10       # chế độ tiết kiệm: AI viết chừng này kịch bản lõi, phần còn lại do Expander sinh theo luật
FALLBACK_COUNT = 8      # AI lỗi và người dùng không chọn số lượng: Expander sinh chừng này kịch bản
MAX_GAP_CASES = 5


class Trace:
    """Vết thực thi. on_step được gọi mỗi khi có thay đổi, để giao diện hiện tiến độ trực tiếp."""

    def __init__(self, on_step=None):
        self.steps: list[dict] = []
        self.on_step = on_step

    def _notify(self):
        if self.on_step:
            self.on_step([dict(s) for s in self.steps])

    def start(self, agent: str, summary: str) -> None:
        self.steps.append({"agent": agent, "status": "running", "ms": 0, "summary": summary})
        self._notify()

    def add(self, agent: str, status: str, ms: int, summary: str, **extra) -> None:
        entry = {"agent": agent, "status": status, "ms": ms, "summary": summary, **extra}
        if self.steps and self.steps[-1]["agent"] == agent and self.steps[-1]["status"] == "running":
            self.steps[-1] = entry
        else:
            self.steps.append(entry)
        self._notify()


def _ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


def _model(llm) -> str | None:
    used = getattr(llm, "last_used", None) or llm
    return f"{used.name}/{used.model}" if used else None


def default_criteria(text: str) -> list[str]:
    """Tách tiêu chí khi không có AI: mỗi dòng gạch đầu dòng là một tiêu chí."""
    lines = [re.sub(r"^\s*[-*•\d.)]+\s*", "", ln).strip() for ln in text.splitlines() if re.match(r"^\s*[-*•\d]", ln)]
    return [ln for ln in lines if ln]


def make_plan(text: str, categories: list[str], spec: dict | None, count: int | None, llm) -> dict:
    """Lead lập kế hoạch. Code kiểm tra đầu ra: số lượng có trần, nhóm ngoài phạm vi chỉ là gợi ý."""
    plan = {"summary": "", "criteria": default_criteria(text), "focus": [], "suggest": [], "count": count, "source": "default"}
    if llm is None:
        return plan
    api = summarize_openapi(spec, limit=2500) if spec else "(no API documentation)"
    data = llm.complete_json(prompts.LEAD_SYSTEM, prompts.LEAD_USER.format(
        requirement=text[:4000], api=api, categories=", ".join(categories)))
    if not isinstance(data, dict):
        return plan
    criteria = [str(c).strip() for c in data.get("criteria") or [] if str(c).strip()][:20]
    plan.update(summary=str(data.get("summary") or "")[:300], source="ai",
                criteria=criteria or plan["criteria"],
                focus=[str(f).strip() for f in data.get("focus") or [] if str(f).strip()][:8],
                suggest=[s for s in data.get("suggest") or [] if s in ("security", "performance") and s not in categories])
    if count is None:
        try:     # đủ để phủ các tiêu chí, nhưng không để AI tự tăng tuỳ ý
            plan["count"] = max(4, min(int(data.get("count") or 0), 12)) if data.get("count") else None
        except (TypeError, ValueError):
            pass
    return plan


def parse_p95(text: str) -> int | None:
    """Ngưỡng thời gian nêu trong yêu cầu: "dưới 500ms", "trong 2 giây"."""
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(ms|mili|giây|s\b)", text or "", re.I)
    if not m:
        return None
    value = float(m.group(1).replace(",", "."))
    return int(value if m.group(2).lower().startswith("m") else value * 1000)


def generate_pipeline(text: str, url: str, *, count: int | None = None, categories: list[str] | None = None,
                      spec: dict | None = None, samples: str = "", provider: LLMProvider | None = None,
                      ai_review_enabled: bool = True, auto_fix: bool = True,
                      seed_cases: list[TestCase] | None = None, llm_enabled: bool = True, lead: bool = True,
                      verifier=None, verify_note: str = "", on_step=None, economy: bool = False, items: list[dict] | None = None) -> dict:
    """Trả về {cases, reviews, criteria, plan, trace, stats, warnings}.
    verifier(list[TestCase]) -> {id: {status, ...}}: chạy thử thật; None thì bỏ qua bước này."""
    categories = categories or ["functional"]
    trace, warnings, cases = Trace(on_step), [], []
    stats: dict = {"requested": count, "categories": categories}
    host = urlparse(url).netloc
    prefix = _prefix_for(text + url)
    n_endpoints = sum(len(m) for p, m in review.endpoints(spec).items() if not is_excluded(p))
    trace.add("context", "ok", 0, (f"OpenAPI: {n_endpoints} endpoint" if spec else "Không có OpenAPI")
              + (" · có dữ liệu thật" if samples else ""))

    llm = None
    if llm_enabled:
        try:
            llm = provider or get_provider()
        except Exception as e:
            warnings.append(f"Chưa cấu hình AI: {e}")

    # Số lượng lớn: chỉ dùng Expander khi có OpenAPI để sinh theo luật; không có thì AI viết toàn bộ như trước
    expand = bool(economy and count and count > ECONOMY_CORE and spec and "functional" in categories)
    plan = {"summary": "", "criteria": default_criteria(text), "focus": [], "suggest": [], "count": count, "source": "default"}
    if lead and llm is not None:
        t0 = time.perf_counter()
        trace.start("lead", "Đọc yêu cầu, lập kế hoạch…")
        try:
            plan = make_plan(text, categories, spec, count, llm)
            trace.add("lead", "ok", _ms(t0), f"Kế hoạch: {len(plan['criteria'])} tiêu chí, giao "
                      + ", ".join(categories) + (f"; {plan['summary']}" if plan["summary"] else ""), model=_model(llm))
        except Exception as e:
            warnings.append(f"Lead lỗi, dùng kế hoạch mặc định: {e}")
            trace.add("lead", "error", _ms(t0), f"Dùng kế hoạch mặc định: {str(e)[:120]}")
    focus = ""
    if plan["focus"] or plan["criteria"]:
        focus = "Test plan from the lead: cover every criterion below."
        focus += "".join(f"\n- {c}" for c in plan["criteria"])
        focus += "".join(f"\nFocus: {f}" for f in plan["focus"])

    if seed_cases:         # chế độ mock: dùng dữ liệu mẫu thay cho Writer
        cases += seed_cases
        trace.add("writer", "ok", 0, f"{len(seed_cases)} kịch bản mẫu (chế độ mock)")
    elif "functional" in categories:
        t0 = time.perf_counter()
        writer_ok = False
        guidance, used, n_lessons = skills.context("writer", text, host)
        trace.start("writer", "Viết kịch bản chức năng…")
        try:
            if llm is None:
                raise RuntimeError("chưa cấu hình AI")
            written = generate_test_cases(text, openapi_spec=spec, count=ECONOMY_CORE if expand else plan["count"], sample_data=samples or None,
                                          provider=llm, id_prefix=prefix, guidance=f"{focus}\n\n{guidance}".strip(), stats=stats)
            cases += written
            writer_ok = True
            trace.add("writer", "ok", _ms(t0), f"Viết {len(written)} kịch bản", skills=used, lessons=n_lessons, model=_model(llm))
        except Exception as e:
            warnings.append(f"Writer lỗi: {e}")
            trace.add("writer", "error", _ms(t0), str(e)[:200], skills=used)
        # Số lượng nhỏ mà AI không viết được: vẫn có kịch bản theo luật thay vì báo lỗi
        if not writer_ok and economy and spec and not expand:
            expand = True
            count = count or plan["count"] or FALLBACK_COUNT

    probe_ids: set[str] = set()
    if expand:
        t0 = time.perf_counter()
        trace.start("expander", "Sinh kịch bản theo OpenAPI và dữ liệu thật…")
        need = count - len(cases)
        have = {c.title.strip().lower() for c in cases}
        extra = [c for c in expander.build_cases(spec, text, items, limit=need + len(cases)) if c.title.strip().lower() not in have][:need]
        for i, tc in enumerate(extra, 1):
            tc.id = f"{prefix}X-{i:03d}"
            probe_ids.add(tc.id)      # kết quả mong đợi lấy từ OpenAPI và dữ liệu thật: AI không viết lại
        cases += extra
        trace.add("expander", "ok", _ms(t0), f"Sinh {len(extra)} kịch bản theo luật, không gọi AI")
        stats["rule_cases"] = len(extra)
        if len(cases) < count:
            warnings.append(f"Chỉ có {len(cases)}/{count} kịch bản chức năng: đã hết các hành vi khác nhau, không lặp lại để đủ số.")
    if "security" in categories:
        t0 = time.perf_counter()
        trace.start("security", "Dò điểm yếu theo OWASP…")
        sec = security_tests.build_security_cases(spec, url, security_tests.sample_ids_from(samples))
        n_probe = len(sec)
        note = f"{n_probe} kịch bản dò theo OWASP"
        extra_skills = []
        if llm is not None:
            guidance, extra_skills, _ = skills.context("security", text, host)
            try:
                ctx = (("API:\n" + summarize_openapi(spec, limit=4000)) if spec else "") + \
                      (("\n\nReal data:\n" + samples[:2000]) if samples else "") + "\n\n" + guidance
                raw = unwrap_list(llm.complete_json(prompts.TEST_CASES_SYSTEM, prompts.SECURITY_USER.format(
                    requirement=text, context=ctx, min_cases=2, max_cases=5)), "test_cases")
                extra, _ = _validate_all(raw)
                for tc in extra:
                    tc.category = "security"
                sec += extra
                note += f" + {len(extra)} kịch bản nghiệp vụ"
            except Exception as e:
                warnings.append(f"Security (AI) lỗi, vẫn giữ kịch bản dò tự động: {e}")
        for i, tc in enumerate(sec, 1):
            tc.id = f"{prefix}S-{i:02d}"
            if i <= n_probe:
                probe_ids.add(tc.id)      # kịch bản dò: không đạt là phát hiện, AI không được viết lại
        cases += sec
        trace.add("security", "ok", _ms(t0), note, skills=extra_skills, model=_model(llm) if llm else None)

    if "performance" in categories:
        t0 = time.perf_counter()
        p95 = parse_p95(text)
        perf = security_tests.build_performance_cases(spec, url, p95_ms=p95)
        for i, tc in enumerate(perf, 1):
            tc.id = f"{prefix}P-{i:02d}"
            probe_ids.add(tc.id)
        cases += perf
        trace.add("performance", "ok", _ms(t0), f"{len(perf)} kịch bản đo hiệu năng"
                  + (f", ngưỡng {p95}ms theo yêu cầu" if p95 else ", ngưỡng mặc định"))

    stats["ai_cases"] = sum(c.id not in probe_ids for c in cases)
    out = review_and_fix(cases, text, spec, llm, trace, host, ai_review_enabled=ai_review_enabled, auto_fix=auto_fix,
                         keep=probe_ids)
    cases, reviews, criteria = out["cases"], out["reviews"], out["criteria"]
    warnings += out["warnings"]

    # Lead: tiêu chí chưa có kịch bản thì giao Writer viết thêm một lần
    uncovered = [c["text"] for c in criteria if not c["covered_by"]]
    if lead and uncovered and llm is not None and "functional" in categories and not seed_cases:
        t0 = time.perf_counter()
        trace.start("lead", f"{len(uncovered)} tiêu chí chưa phủ, giao Writer viết thêm…")
        try:
            focus_gap = text + "\n\nOnly write test cases for these acceptance criteria that no case covers yet:\n" + \
                "\n".join(f"- {u}" for u in uncovered[:MAX_GAP_CASES])
            guidance = skills.context("writer", text, host)[0]
            gap = generate_test_cases(focus_gap, openapi_spec=spec, count=min(len(uncovered), MAX_GAP_CASES),
                                      sample_data=samples or None, provider=llm, id_prefix=prefix + "G", guidance=guidance, stats=stats)
            cases += gap
            reviews.update(review.review_cases(gap, spec))
            covered_now = {u for u in uncovered}
            for c in criteria:
                if c["text"] in covered_now and not c["covered_by"]:
                    c["covered_by"] = [g.id for g in gap]
                    c["gap_filled"] = True
            trace.add("lead", "ok", _ms(t0), f"Writer viết thêm {len(gap)} kịch bản cho tiêu chí còn thiếu", model=_model(llm))
        except Exception as e:
            warnings.append(f"Không viết thêm được cho tiêu chí còn thiếu: {e}")
            trace.add("lead", "error", _ms(t0), str(e)[:160])

    if verifier is not None and cases:
        try:
            vs = verify_and_repair(cases, reviews, text, spec, llm if auto_fix else None, trace, verifier, probe_ids)
            stats.update(verify_first=vs["first"], verify_final=vs["final"], repaired=vs["repaired"])
            warnings += vs["warnings"]
        except Exception as e:    # chạy thử lỗi (thiếu trình duyệt, mất kết nối...) không làm mất kịch bản đã sinh
            warnings.append(f"Không chạy thử được: {e}")
            trace.add("verifier", "error", 0, f"Không chạy thử được: {str(e)[:160]}")
    elif verify_note:
        trace.add("verifier", "skip", 0, verify_note)

    counts = _counts(reviews)
    hits, misses = getattr(llm, "hits", None), getattr(llm, "misses", None)
    if hits is not None:
        stats.update(llm_calls=misses, llm_reused=hits)
    if lead:
        trace.add("lead", "ok", 0, f"Kết luận: {counts['approve']} sẵn sàng, {counts['needs_fix'] + counts['reject']} cần người xem"
                  + (f"; gợi ý thêm nhóm: {', '.join(plan['suggest'])}" if plan["suggest"] else "")
                  + (f"; gọi AI {misses} lần, dùng lại {hits} lần" if hits is not None else ""))
    stats.update(produced=len(cases))
    return {"cases": cases, "reviews": reviews, "criteria": criteria, "plan": plan, "trace": trace.steps,
            "stats": stats, "warnings": warnings}


def review_and_fix(cases: list[TestCase], text: str, spec: dict | None, llm, trace: Trace, host: str = "",
                   *, ai_review_enabled: bool = True, auto_fix: bool = True, keep: set[str] | None = None) -> dict:
    """keep: kịch bản Fixer không được đụng (kịch bản dò bảo mật)."""
    warnings: list[str] = []
    criteria: list[dict] = []
    t0 = time.perf_counter()
    trace.start("reviewer", f"Duyệt {len(cases)} kịch bản…")
    reviews = review.review_cases(cases, spec)
    used: list[str] = []
    api = summarize_openapi(spec, limit=3000) if spec else ""
    guidance = ""
    use_ai = llm is not None and ai_review_enabled and bool(cases) and bool(text.strip())
    # Kịch bản sinh theo luật không cần AI đọc lại: chỉ tốn hạn mức
    ai_part = [c for c in cases if c.id not in (keep or set())]
    use_ai = use_ai and bool(ai_part)
    if use_ai:
        guidance, used, _ = skills.context("reviewer", text, host)
        try:
            ai = review.ai_review(ai_part, text, api, guidance, provider=llm)
            criteria = ai["criteria"]
            for cid, extra in ai["reviews"].items():
                reviews[cid] = review.merge(reviews[cid], extra)
        except Exception as e:
            warnings.append(f"Reviewer (AI) lỗi, dùng kết quả luật tự động: {e}")
    counts = _counts(reviews)
    trace.add("reviewer", "ok", _ms(t0), f"Đạt {counts['approve']} · cần sửa {counts['needs_fix']} · loại {counts['reject']}",
              skills=used, model=_model(llm) if llm else None)

    bad = [c for c in cases if reviews[c.id]["verdict"] != "approve" and c.id not in (keep or set())]
    if auto_fix and llm is not None and bad:
        t0 = time.perf_counter()
        trace.start("fixer", f"Sửa {len(bad)} kịch bản bị chê…")
        try:
            changed = _fix(bad, cases, reviews, text, spec, llm)
            if changed and use_ai:      # nhận xét cũ của AI chưa chắc còn đúng: nhờ AI xem lại bản đã sửa
                try:
                    again = review.ai_review([c for c in cases if c.id in changed], text, api, guidance, provider=llm)
                    for cid in changed:
                        lint_only = [i for i in reviews[cid]["issues"] if i["code"] != "AI"]
                        issues = lint_only + again["reviews"].get(cid, [])
                        score, verdict = review.score_of(issues)
                        reviews[cid].update(score=score, verdict=verdict, issues=issues)
                except Exception as e:
                    warnings.append(f"Chưa xem lại được bản sửa, giữ nhận xét cũ: {e}")
            better = sum(reviews[c]["score"] > reviews[c].get("fixed_from", 0) for c in changed)
            trace.add("fixer", "ok", _ms(t0), f"Viết lại {len(changed)}/{len(bad)} kịch bản, {better} kịch bản tăng điểm", model=_model(llm))
        except Exception as e:
            warnings.append(f"Fixer lỗi, giữ bản gốc: {e}")
            trace.add("fixer", "error", _ms(t0), str(e)[:200])
    return {"cases": cases, "reviews": reviews, "criteria": criteria, "warnings": warnings}


def _counts(reviews: dict) -> dict:
    out = {"approve": 0, "needs_fix": 0, "reject": 0}
    for r in reviews.values():
        out[r["verdict"]] += 1
    return out


# ---------- Giữ cho bản sửa không làm yếu kịch bản ----------
def assertion_count(tc: TestCase) -> int:
    n = 0
    for s in tc.steps:
        if s.perf:
            n += 1
        if s.action in ("assert_text", "assert_visible"):
            n += 1
        if isinstance(s.expect, dict):
            for k, v in s.expect.items():
                if v in (None, "", [], {}):
                    continue
                n += len(v) if k == "json_contains" and isinstance(v, (dict, list)) else 1
    return n


def _statuses(tc: TestCase) -> dict[tuple, object]:
    out = {}
    for s in tc.steps:
        if s.method and isinstance(s.expect, dict) and s.expect.get("status"):
            out[(s.method, re.sub(r"\{\{.*?\}\}", "*", s.path or ""))] = s.expect["status"]
    return out


def weakened(old: TestCase, new: TestCase, requirement: str) -> str | None:
    """Lý do từ chối bản sửa, hoặc None nếu chấp nhận được."""
    if assertion_count(new) < assertion_count(old):
        return "giảm số kiểm tra"
    before, after = _statuses(old), _statuses(new)
    for key, s1 in before.items():
        s2 = after.get(key)
        if s2 is not None and s2 != s1 and re.search(rf"\b{s1}\b", requirement) and not re.search(rf"\b{s2}\b", requirement):
            return f"đổi kết quả mong đợi {s1} mà yêu cầu đã nêu sang {s2}"
    return None


def _fix(bad: list[TestCase], cases: list[TestCase], reviews: dict, text: str, spec, llm, chunk: int = 8) -> list[str]:
    """AI viết lại theo nhận xét. Nhận xét của AI được giữ nguyên cho tới khi được xem lại,
    nên viết lại không tự làm tăng điểm. Trả về id các kịch bản đã thay."""
    context = ("API:\n" + summarize_openapi(spec, limit=4000)) if spec else ""
    index = {c.id: i for i, c in enumerate(cases)}
    changed: list[str] = []
    for start in range(0, min(len(bad), 24), chunk):
        part = bad[start:start + chunk]
        items = "\n".join(json.dumps({"test_case": c.model_dump(exclude_none=True),
                                      "problems": [i["message"] for i in reviews[c.id]["issues"]]},
                                     ensure_ascii=False, default=str) for c in part)
        raw = unwrap_list(llm.complete_json(prompts.TEST_CASES_SYSTEM, prompts.FIX_USER.format(
            requirement=text[:3000], context=context, items=items[:12000])), "test_cases")
        new_cases, _ = _validate_all(raw)
        by_id = {c.id: c for c in part}
        for n in new_cases:
            old = by_id.get(n.id)
            if old is None or n.type != old.type or weakened(old, n, text):
                continue
            n.category, n.requirement_id, n.technique = old.category, old.requirement_id, old.technique
            lint_old, lint_new = review.lint(old, spec, cases), review.lint(n, spec, cases)
            if review.score_of(lint_new)[0] < review.score_of(lint_old)[0]:
                continue
            before = reviews[old.id]
            issues = lint_new + [i for i in before["issues"] if i["code"] == "AI"]
            score, verdict = review.score_of(issues)
            cases[index[old.id]] = n
            reviews[old.id] = {"score": score, "verdict": verdict, "issues": issues, "source": "fixer", "fixed_from": before["score"]}
            changed.append(old.id)
    return changed


def _tally(status: dict) -> dict:
    out = {"passed": 0, "app_bug": 0, "test_broken": 0, "flaky": 0, "skipped": 0}
    for s in status.values():
        out[s.get("status", "skipped")] = out.get(s.get("status", "skipped"), 0) + 1
    return out


def _repair(broken: list[TestCase], status: dict, text: str, spec, llm) -> dict[str, TestCase]:
    """Sửa theo bằng chứng chạy thử. Bản đổi kết quả mong đợi hoặc giảm kiểm tra bị loại ngay."""
    context = ("API:\n" + summarize_openapi(spec, limit=4000)) if spec else ""
    items = "\n".join(json.dumps({"test_case": c.model_dump(exclude_none=True), "run_result": status[c.id].get("evidence")},
                                 ensure_ascii=False, default=str) for c in broken[:8])
    raw = unwrap_list(llm.complete_json(prompts.TEST_CASES_SYSTEM, prompts.REPAIR_RUN_USER.format(
        requirement=text[:3000], context=context, items=items[:14000])), "test_cases")
    new_cases, _ = _validate_all(raw)
    by_id = {c.id: c for c in broken}
    out = {}
    for n in new_cases:
        old = by_id.get(n.id)
        if old is not None and n.type == old.type and not weakened(old, n, text):
            n.category, n.requirement_id, n.technique = old.category, old.requirement_id, old.technique
            out[n.id] = n
    return out


def verify_and_repair(cases: list[TestCase], reviews: dict, text: str, spec, llm, trace: Trace, verifier,
                      probe_ids: set[str] | None = None, max_rounds: int = MAX_REPAIR_ROUNDS) -> dict:
    """Chạy thử → Triage → sửa lỗi do kịch bản → chạy lại. Lỗi ứng dụng được giữ nguyên, tuyệt đối không sửa cho đạt.
    Điểm duyệt cuối cùng phản ánh kết quả chạy thử."""
    warnings: list[str] = []
    probe_ids = probe_ids or set()
    index = {c.id: i for i, c in enumerate(cases)}
    targets = [c for c in cases if c.category != "performance"]
    t0 = time.perf_counter()
    trace.start("verifier", f"Chạy thử {len(targets)} kịch bản trên hệ thống…")
    status = verifier(targets)
    first_status = dict(status)
    first = _tally(status)
    trace.add("verifier", "ok", _ms(t0), _describe_tally(first))

    repaired = 0
    for round_no in range(1, max_rounds + 1):
        broken = [c for c in cases if status.get(c.id, {}).get("status") == "test_broken" and c.id not in probe_ids]
        if not broken or llm is None:
            break
        t0 = time.perf_counter()
        trace.start("fixer", f"Vòng {round_no}: sửa {len(broken)} kịch bản theo lỗi chạy thử…")
        try:
            candidates = _repair(broken, status, text, spec, llm)
        except Exception as e:
            warnings.append(f"Fixer lỗi, giữ bản gốc: {e}")
            trace.add("fixer", "error", _ms(t0), str(e)[:160])
            break
        if not candidates:
            trace.add("fixer", "ok", _ms(t0), f"Vòng {round_no}: không có bản sửa hợp lệ", model=_model(llm))
            break
        rerun = verifier(list(candidates.values()))
        ok = 0
        for cid, new in candidates.items():
            if rerun.get(cid, {}).get("status") != "passed":
                continue       # chạy lại vẫn lỗi: giữ bản gốc, để người xem
            old = cases[index[cid]]
            changed_expect = {k: (v, _statuses(new).get(k)) for k, v in _statuses(old).items()
                              if _statuses(new).get(k) not in (None, v)}
            cases[index[cid]] = new
            issues = review.lint(new, spec, cases)
            for (method, path), (a, b) in changed_expect.items():
                issues.append({"code": "V02", "severity": "medium", "step": None,
                               "message": f"Kết quả mong đợi của {method} {path} đổi từ {a} sang {b} theo hành vi thực tế; cần người xác nhận đúng với yêu cầu."})
            score, verdict = review.score_of(issues)
            reviews[cid] = {"score": score, "verdict": verdict, "issues": issues, "source": "fixer+verifier"}
            status[cid] = rerun[cid]
            ok += 1
            repaired += 1
        trace.add("fixer", "ok", _ms(t0), f"Vòng {round_no}: sửa {len(candidates)}, chạy lại đạt {ok}", model=_model(llm))
        if ok == 0:
            break

    for cid, s in status.items():
        r = reviews.get(cid)
        if r is None:
            continue
        r["verification"] = s.get("status")
        if s.get("status") == "test_broken":
            r["issues"] = r["issues"] + [{"code": "V01", "severity": "high", "step": None,
                                          "message": f"Chạy thử cho thấy kịch bản còn lỗi: {s.get('detail', '')}"[:300]}]
        elif s.get("status") == "flaky":
            r["issues"] = r["issues"] + [{"code": "V03", "severity": "low", "step": None,
                                          "message": "Lần đầu không đạt nhưng chạy lại đạt: kết quả không ổn định."}]
        elif s.get("status") == "app_bug":
            r["finding"] = s.get("detail", "")
        r["score"], r["verdict"] = review.score_of(r["issues"])
    final = _tally(status)
    trace.add("verifier", "ok", 0, "Sau khi sửa: " + _describe_tally(final))
    # Số liệu "AI viết đúng" chỉ tính kịch bản do AI viết, không tính kịch bản sinh theo luật
    ai_first = _tally({k: v for k, v in first_status.items() if k not in probe_ids})
    ai_final = _tally({k: v for k, v in status.items() if k not in probe_ids})
    return {"first": ai_first, "final": ai_final, "all_first": first, "all_final": final, "repaired": repaired, "warnings": warnings}


def _describe_tally(t: dict) -> str:
    parts = [f"đạt {t['passed']}", f"phát hiện lỗi ứng dụng {t['app_bug']}", f"lỗi kịch bản {t['test_broken']}"]
    if t["flaky"]:
        parts.append(f"không ổn định {t['flaky']}")
    if t["skipped"]:
        parts.append(f"bỏ qua {t['skipped']}")
    return " · ".join(parts)


def learn(evidence: list[str], provider: LLMProvider | None = None) -> list[str]:
    """Rút bài học từ bằng chứng thật. AI lỗi thì trả về chính bằng chứng để người duyệt tự quyết."""
    evidence = [e.strip() for e in evidence if e and e.strip()][:30]
    if not evidence:
        return []
    try:
        llm = provider or get_provider()
        data = llm.complete_json(prompts.LEARN_SYSTEM, prompts.LEARN_USER.format(
            evidence="\n".join(f"- {e[:400]}" for e in evidence)))
        lessons = data.get("lessons") if isinstance(data, dict) else data
        return [str(x).strip() for x in lessons or [] if str(x).strip()][:5]
    except Exception:
        return [e[:200] for e in evidence[:5]]

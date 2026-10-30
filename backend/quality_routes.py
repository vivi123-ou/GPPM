"""API cho chất lượng, kiến thức (skill, bài học) và bảo trì kịch bản.

/api/quality     số liệu đo được, phép đo phát hiện lỗi, duyệt kịch bản, nhật ký agent
/api/knowledge   skill, bài học, xuất bộ dữ liệu huấn luyện
/api/maintenance yêu cầu thay đổi, API thay đổi, locator, bản sửa self-healing
"""
import json
import os
import re
from difflib import unified_diff
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from backend import ai_client
from backend.db import get_conn
from backend.models import TestCase
from backend.security import check_target, client_ip

quality = APIRouter(prefix="/api/quality", tags=["Quality"])
knowledge = APIRouter(prefix="/api/knowledge", tags=["Knowledge"])
maintenance = APIRouter(prefix="/api/maintenance", tags=["Maintenance"])


def _default_url() -> str:
    return (os.getenv("DEMO_SHOP_URL") or "http://127.0.0.1:8000").rstrip("/") + "/shop"


def _rows(sql: str, *args) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(sql, args).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _exec(sql: str, *args) -> int:
    conn = get_conn()
    cur = conn.execute(sql, args)
    conn.commit()
    conn.close()
    return cur.lastrowid or cur.rowcount


def _req_host(text: str) -> str:
    m = re.match(r"^\[Autopilot\]\s+(\S+)", text or "") or re.match(r"^\[(https?:[^\]]+)\]", text or "")
    if m:
        return urlparse(m.group(1)).netloc
    return urlparse(_default_url()).netloc


def _strip_prefix(text: str) -> tuple[str, str]:
    """Tách "[url] " ở đầu nội dung yêu cầu: (url, nội dung)."""
    m = re.match(r"^\[(https?:[^\]]+)\]\s*(.*)$", text or "", re.S)
    return (m.group(1), m.group(2)) if m else ("", text or "")


def _active_cases(host: str | None = None) -> list[TestCase]:
    rows = _rows("SELECT t.json, r.text FROM test_cases t LEFT JOIN requirements r ON t.requirement_id = 'REQ-' || r.id "
                 "WHERE t.status='active' ORDER BY t.id")
    return [TestCase.model_validate_json(r["json"]) for r in rows if host is None or _req_host(r["text"]) == host]


# ---------------- Duyệt kịch bản ----------------
def save_reviews(reviews: dict[str, dict]) -> None:
    conn = get_conn()
    for cid, r in reviews.items():
        conn.execute("INSERT INTO reviews(test_case_id, score, verdict, issues_json, source, verification) VALUES (?,?,?,?,?,?) "
                     "ON CONFLICT(test_case_id) DO UPDATE SET score=excluded.score, verdict=excluded.verdict, "
                     "issues_json=excluded.issues_json, source=excluded.source, "
                     "verification=COALESCE(excluded.verification, reviews.verification), updated_at=CURRENT_TIMESTAMP",
                     (cid, r["score"], r["verdict"], json.dumps(r["issues"], ensure_ascii=False), r.get("source"), r.get("verification")))
    conn.commit()
    conn.close()


@quality.get("/reviews")
def list_reviews():
    return {r["test_case_id"]: {**r, "issues": json.loads(r.pop("issues_json") or "[]")}
            for r in _rows("SELECT * FROM reviews")}


class ReviewIn(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=200)
    url: str | None = None
    use_ai: bool = False
    requirement: str | None = None


@quality.post("/review")
def review_now(body: ReviewIn, request: Request):
    """Duyệt lại các kịch bản đã chọn. use_ai=true: thêm AI đối chiếu với yêu cầu gốc."""
    from ai.autopilot import find_openapi
    from ai.review import ai_review, merge, review_cases
    from ai.skills import context
    url = body.url or _default_url()
    check_target(url, client_ip(request))
    wanted = set(body.ids)
    cases = [c for c in _active_cases() if c.id in wanted]
    if not cases:
        raise HTTPException(404, "Không thấy kịch bản nào")
    spec = find_openapi(url)
    reviews = review_cases(cases, spec)
    criteria, warning = [], None
    if body.use_ai and not ai_client.USE_MOCK:
        text = body.requirement
        if not text and cases[0].requirement_id:
            row = _rows("SELECT text FROM requirements WHERE 'REQ-' || id = ?", cases[0].requirement_id)
            text = _strip_prefix(row[0]["text"])[1] if row else ""
        try:
            ai = ai_review(cases, text or "", guidance=context("reviewer", text or "", urlparse(url).netloc)[0])
            criteria = ai["criteria"]
            for cid, extra in ai["reviews"].items():
                reviews[cid] = merge(reviews[cid], extra)
        except Exception as e:
            warning = f"AI không phản hồi, dùng kết quả luật tự động: {e}"
    save_reviews(reviews)
    return {"reviews": reviews, "criteria": criteria, "warning": warning}


class DecisionIn(BaseModel):
    decision: str = Field(pattern="^(approved|rejected)$")
    reason: str = Field(default="", max_length=500)


@quality.post("/review/{tc_id}/decision")
def review_decision(tc_id: str, body: DecisionIn):
    """Người duyệt có quyết định cuối. Từ chối kèm lý do sẽ trở thành bài học chờ duyệt."""
    if not _rows("SELECT 1 FROM test_cases WHERE id=?", tc_id):
        raise HTTPException(404, "Không thấy kịch bản")
    _exec("INSERT INTO reviews(test_case_id, decision, decision_reason) VALUES (?,?,?) "
          "ON CONFLICT(test_case_id) DO UPDATE SET decision=excluded.decision, decision_reason=excluded.decision_reason, "
          "updated_at=CURRENT_TIMESTAMP", tc_id, body.decision, body.reason)
    if body.decision == "rejected" and body.reason.strip():
        _exec("INSERT INTO lessons(text, agent, source, status) VALUES (?,?,?,'pending')",
              body.reason.strip(), "writer", f"human:{tc_id}")
    return {"ok": True}


# ---------------- Số liệu ----------------
def _endpoint_coverage(url: str) -> dict | None:
    from ai.autopilot import find_openapi
    from ai.classifier import _path_match
    from ai.test_generator import is_excluded
    spec = find_openapi(url)
    if not spec:
        return None
    all_eps = [(m.upper(), p) for p, ops in spec.get("paths", {}).items() if not is_excluded(p)
               for m in ops if m.lower() in ("get", "post", "put", "patch", "delete")]
    used = set()
    for c in _active_cases(urlparse(url).netloc):
        for s in c.steps:
            if s.method and s.path:
                path = re.sub(r"\{\{\s*[\w$]+\s*\}\}", "1", s.path).split("?")[0]
                for m, p in all_eps:
                    if m == s.method.upper() and _path_match(p, path):
                        used.add((m, p))
    return {"total": len(all_eps), "covered": len(used), "pct": round(len(used) / len(all_eps) * 100) if all_eps else 0,
            "missing": [f"{m} {p}" for m, p in all_eps if (m, p) not in used]}


SAMPLE_PREFIX = "TC-DEMO"      # bộ mẫu do người viết: không tính vào số liệu của AI


_RULE_ID = re.compile(r"^TC-[0-9A-F]{4}X-")        # Expander sinh theo luật, không phải AI viết


def _is_ai(case_id: str) -> bool:
    return not case_id.startswith(SAMPLE_PREFIX) and not _RULE_ID.match(case_id)


def _pct(a: int, b: int) -> int | None:
    return round(a / b * 100) if b else None


@quality.get("/metrics")
def metrics(url: str | None = None):
    """Tỉ lệ đo được từ dữ liệu thật, không phải con số ước lượng. Chưa có dữ liệu thì trả về None."""
    url = url or _default_url()
    host = urlparse(url).netloc

    gens = _rows("SELECT stats_json, requirement_id FROM agent_runs WHERE kind='generate' ORDER BY id DESC LIMIT 50")
    first_valid = first_invalid = requested = produced = 0
    criteria_total = criteria_covered = 0
    # Chạy thử ngay sau khi sinh: kịch bản "đúng" là đạt hoặc bắt được lỗi ứng dụng
    v_total = v_first = v_final = repaired = 0
    for g in _rows("SELECT stats_json FROM agent_runs WHERE kind IN ('generate','autopilot') ORDER BY id DESC LIMIT 50"):
        s = json.loads(g["stats_json"] or "{}")
        a, b = s.get("verify_first"), s.get("verify_final")
        if a and b:
            v_total += sum(a[k] for k in ("passed", "app_bug", "test_broken", "flaky"))
            v_first += a["passed"] + a["app_bug"]
            v_final += b["passed"] + b["app_bug"]
            repaired += s.get("repaired", 0)
    for g in gens:
        s = json.loads(g["stats_json"] or "{}")
        first_valid += s.get("first_valid", 0)
        first_invalid += s.get("first_invalid", 0)
        requested += s.get("requested") or 0
        if s.get("requested"):
            produced += s.get("writer_produced", 0)
    for g in gens[:1]:
        s = json.loads(g["stats_json"] or "{}")
        criteria_total, criteria_covered = s.get("criteria_total", 0), s.get("criteria_covered", 0)

    active_ids = {c.id: c for c in _active_cases(host) if _is_ai(c.id)}
    reviews = [r for r in _rows("SELECT * FROM reviews") if r["test_case_id"] in active_ids and r["verdict"]]
    decisions = [r for r in reviews if r["decision"]]

    latest = _rows("SELECT r.* FROM results r JOIN (SELECT test_case_id, data_set, MAX(id) mid FROM results "
                   "GROUP BY test_case_id, data_set) x ON r.id = x.mid")
    latest = [r for r in latest if r["test_case_id"] in active_ids]
    verdicts = {"app_bug": 0, "test_broken": 0, "flaky": 0, "unknown": 0}
    for r in latest:
        if r["status"] == "failed":
            v = json.loads(r["ai_analysis_json"] or "{}").get("verdict")
            verdicts[v if v in verdicts else "unknown"] += 1
    passed = sum(r["status"] == "passed" for r in latest)
    judged = len(latest) - verdicts["unknown"]

    heals = _rows("SELECT status FROM healing_patches")
    bench = _rows("SELECT summary_json, created_at FROM benchmarks ORDER BY id DESC LIMIT 1")
    runs = _rows("SELECT id, started_at, target, summary, cases_total FROM runs ORDER BY id DESC LIMIT 12")
    return {
        "target": url, "host": host,
        "generation": {
            "schema_valid_pct": _pct(first_valid, first_valid + first_invalid), "first_valid": first_valid,
            "first_invalid": first_invalid, "generations": len(gens),
            "fulfil_pct": _pct(produced, requested), "requested": requested, "produced": produced},
        "review": {
            "reviewed": len(reviews), "active": len(active_ids),
            "approve_pct": _pct(sum(r["verdict"] == "approve" for r in reviews), len(reviews)),
            "avg_score": round(sum(r["score"] or 0 for r in reviews) / len(reviews)) if reviews else None,
            "human_decisions": len(decisions),
            "human_accept_pct": _pct(sum(r["decision"] == "approved" for r in decisions), len(decisions))},
        "execution": {
            "results": len(latest), "passed": passed, "pass_pct": _pct(passed, len(latest)), **verdicts,
            "usable_pct": _pct(judged - verdicts["test_broken"], judged)},
        "verification": {"total": v_total, "first_ok": v_first, "final_ok": v_final, "repaired": repaired,
                         "first_pct": _pct(v_first, v_total), "final_pct": _pct(v_final, v_total)},
        "requirement_coverage": {"total": criteria_total, "covered": criteria_covered,
                                 "pct": _pct(criteria_covered, criteria_total)},
        "endpoint_coverage": _endpoint_coverage(url),
        "healing": {"proposed": len(heals), "applied": sum(h["status"] == "applied" for h in heals)},
        "benchmark": json.loads(bench[0]["summary_json"]) | {"at": bench[0]["created_at"]} if bench else None,
        "runs": [{**r, "summary": json.loads(r["summary"] or "{}")} for r in runs],
    }


class BenchmarkIn(BaseModel):
    ids: list[str] | None = None
    url: str | None = None
    source: str = Field(default="ai", pattern="^(ai|sample|rules)$")    # AI viết, bộ mẫu viết tay hay sinh theo luật


@quality.post("/benchmark")
def benchmark(body: BenchmarkIn, request: Request):
    """Đo khả năng phát hiện lỗi: bật lần lượt từng lỗi cài sẵn của Demo Shop, chạy lại kịch bản API,
    đếm kịch bản đang đạt chuyển sang không đạt. Không gọi AI, kết quả lặp lại được."""
    from ai.http import client as http
    from ai.quick_runner import run_api_test
    url = body.url or _default_url()
    check_target(url, client_ip(request))
    u = urlparse(url)
    base = f"{u.scheme}://{u.netloc}"
    try:
        flags = http.get(f"{base}/api/shop/bugs", timeout=5).json()
        assert isinstance(flags, dict)
    except Exception:
        raise HTTPException(400, "Phép đo chỉ áp dụng cho Demo Shop (cần /api/shop/bugs).")
    cases = [c for c in _active_cases(u.netloc) if c.type == "api" and c.category != "performance"
             and (c.id in body.ids if body.ids else (
                 _is_ai(c.id) if body.source == "ai" else
                 bool(_RULE_ID.match(c.id)) if body.source == "rules" else c.id.startswith(SAMPLE_PREFIX)))]
    if not cases:
        raise HTTPException(404, "Chưa có kịch bản API cho nguồn này. Hãy tạo kịch bản hoặc nạp bộ mẫu.")

    def reset(active: list[str]):
        def before():
            http.post(f"{base}/api/shop/reset", timeout=5)
            for name in active:
                http.put(f"{base}/api/shop/bugs/{name}", json={"enabled": True}, timeout=5)
        return before

    def run(active: list[str]) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        before = reset(active)
        for c in cases:
            out[c.id] = [r["status"] for r in run_api_test(c, base, before_each=before)]
        return out

    def failing(res):
        return {cid for cid, st in res.items() if "failed" in st}

    from backend.jobs import target_lock
    lock = target_lock(url)
    lock.acquire()
    try:
        base_res = run([])
        base_fail = failing(base_res)
        rows = []
        titles = {c.id: c.title for c in cases}
        for flag in [f for f in flags if f != "ui_v2"]:
            caught = sorted(failing(run([flag])) - base_fail)
            rows.append({"flag": flag, "detected": bool(caught), "by": [{"id": i, "title": titles[i]} for i in caught[:8]],
                         "count": len(caught)})
    finally:
        reset([k for k, v in flags.items() if v])()
        lock.release()
    detected = sum(r["detected"] for r in rows)
    summary = {"seeded": len(rows), "detected": detected, "pct": _pct(detected, len(rows)), "cases": len(cases),
               "source": "chọn riêng" if body.ids else {"ai": "AI viết", "sample": "bộ mẫu viết tay", "rules": "sinh theo luật"}[body.source],
               "baseline_failed": len(base_fail), "rows": rows,
               "note": "Kịch bản đã không đạt ở trạng thái gốc không được tính là phát hiện."}
    _exec("INSERT INTO benchmarks(summary_json) VALUES (?)", json.dumps(summary, ensure_ascii=False))
    return summary


@quality.get("/agents")
def agents_info():
    from ai.agents import CATALOG
    runs = _rows("SELECT id, kind, target, requirement_id, trace_json, stats_json, created_at FROM agent_runs ORDER BY id DESC LIMIT 15")
    return {"catalog": CATALOG, "runs": [{**r, "trace": json.loads(r.pop("trace_json") or "[]"),
                                          "stats": json.loads(r.pop("stats_json") or "{}")} for r in runs]}


@quality.post("/demo-pack")
def demo_pack():
    """Nạp bộ kịch bản mẫu viết sẵn (không cần AI), kèm kịch bản bảo mật và hiệu năng dò tự động."""
    from ai.autopilot import fetch_samples, find_openapi
    from ai.review import review_cases
    from ai.security_tests import build_performance_cases, build_security_cases, sample_ids_from
    from backend.ai_routes import _save_cases
    from backend.demo_pack import REQUIREMENT, build_cases
    url = _default_url()
    spec = find_openapi(url)
    samples = fetch_samples(url, spec) if spec else ""
    cases = build_cases()
    for i, tc in enumerate(build_security_cases(spec, url, sample_ids_from(samples)), 1):
        tc.id = f"TC-DEMOS-{i:02d}"
        cases.append(tc)
    for i, tc in enumerate(build_performance_cases(spec, url), 1):
        tc.id = f"TC-DEMOP-{i:02d}"
        cases.append(tc)
    conn = get_conn()     # nạp lại nhiều lần không sinh rác: lô mẫu cũ được thay thế
    conn.execute("UPDATE test_cases SET status='deleted' WHERE id LIKE 'TC-DEMO%'")
    conn.commit()
    conn.close()
    req_id = _save_cases(cases, f"[{url}] {REQUIREMENT}")
    save_reviews(review_cases(cases, spec))
    return {"requirement_id": req_id, "ids": [c.id for c in cases]}


# ---------------- Skill và bài học ----------------
@knowledge.get("/skills")
def list_skills():
    from ai.skills import AGENTS, all_skills
    return {"agents": AGENTS, "skills": [s.public() for s in all_skills()]}


class SkillIn(BaseModel):
    name: str = Field(min_length=3, max_length=80)
    description: str = Field(default="", max_length=300)
    agents: list[str] = Field(min_length=1)
    triggers: list[str] = []
    body: str = Field(min_length=10, max_length=4000)


@knowledge.post("/skills")
def create_skill(body: SkillIn):
    from ai.skills import AGENTS, all_skills, slug
    bad = [a for a in body.agents if a not in AGENTS]
    if bad:
        raise HTTPException(422, f"Agent không hợp lệ: {bad}")
    sid = slug(body.name)
    if any(s.id == sid and s.builtin for s in all_skills()):
        raise HTTPException(409, "Trùng tên với skill có sẵn")
    _exec("INSERT OR REPLACE INTO skills(id, name, description, agents_json, triggers_json, body, builtin, enabled) "
          "VALUES (?,?,?,?,?,?,0,1)", sid, body.name, body.description, json.dumps(body.agents),
          json.dumps([t.strip() for t in body.triggers if t.strip()], ensure_ascii=False), body.body)
    return {"id": sid}


class ToggleIn(BaseModel):
    enabled: bool


@knowledge.put("/skills/{sid}")
def toggle_skill(sid: str, body: ToggleIn):
    from ai.skills import all_skills
    skill = next((s for s in all_skills() if s.id == sid), None)
    if not skill:
        raise HTTPException(404, "Không thấy skill")
    if skill.builtin:
        _exec("INSERT INTO skills(id, name, builtin, enabled) VALUES (?,?,1,?) "
              "ON CONFLICT(id) DO UPDATE SET enabled=excluded.enabled", sid, skill.name, int(body.enabled))
    else:
        _exec("UPDATE skills SET enabled=? WHERE id=?", int(body.enabled), sid)
    return {"ok": True}


@knowledge.delete("/skills/{sid}")
def delete_skill(sid: str):
    _exec("DELETE FROM skills WHERE id=? AND builtin=0", sid)
    return {"ok": True}


@knowledge.get("/lessons")
def list_lessons():
    return _rows("SELECT * FROM lessons ORDER BY status='pending' DESC, id DESC")


class LessonIn(BaseModel):
    text: str = Field(min_length=5, max_length=500)
    host: str | None = None
    agent: str = "writer"


@knowledge.post("/lessons")
def add_lesson(body: LessonIn):
    return {"id": _exec("INSERT INTO lessons(text, agent, source, host, status) VALUES (?,?,'human',?,'active')",
                        body.text, body.agent, body.host or "")}


class LessonStatus(BaseModel):
    status: str = Field(pattern="^(active|disabled|pending)$")


@knowledge.put("/lessons/{lid}")
def set_lesson(lid: int, body: LessonStatus):
    _exec("UPDATE lessons SET status=? WHERE id=?", body.status, lid)
    return {"ok": True}


@knowledge.delete("/lessons/{lid}")
def delete_lesson(lid: int):
    _exec("DELETE FROM lessons WHERE id=?", lid)
    return {"ok": True}


class LearnIn(BaseModel):
    url: str | None = None
    limit: int = Field(default=30, le=100)


@knowledge.post("/learn")
def learn_now(body: LearnIn):
    """Agent Learner: lấy lỗi kịch bản gần đây và lý do người duyệt từ chối, rút thành bài học chờ duyệt."""
    from ai.agents import learn
    url = body.url or _default_url()
    host = urlparse(url).netloc
    evidence = []
    for r in _rows("SELECT test_case_id, title, error_msg, ai_analysis_json FROM results "
                   "WHERE ai_analysis_json LIKE '%test_broken%' ORDER BY id DESC LIMIT ?", body.limit):
        a = json.loads(r["ai_analysis_json"])
        evidence.append(f"{r['title']}: {r['error_msg']}. {a.get('explanation', '')} {a.get('suggested_fix', '')}")
    evidence += [r["decision_reason"] for r in _rows(
        "SELECT decision_reason FROM reviews WHERE decision='rejected' AND decision_reason != '' ORDER BY updated_at DESC LIMIT 20")]
    if not evidence:
        return {"created": 0, "lessons": [], "message": "Chưa có lỗi kịch bản hay lý do từ chối để học."}
    if ai_client.USE_MOCK:
        lessons = [e[:200] for e in evidence[:5]]
    else:
        lessons = learn(evidence)
    known = {r["text"] for r in _rows("SELECT text FROM lessons")}
    fresh = [t for t in lessons if t not in known]
    for t in fresh:
        _exec("INSERT INTO lessons(text, agent, source, host, status) VALUES (?,?,'learner',?,'pending')", t, "writer", host)
    return {"created": len(fresh), "lessons": fresh, "evidence": len(evidence)}


@knowledge.get("/dataset.jsonl")
def dataset():
    """Xuất các kịch bản đã duyệt dạng JSONL (requirement → test case): dữ liệu sẵn sàng để fine-tune sau này."""
    from ai.prompts import TEST_CASES_SYSTEM
    from ai.quick_runner import redact
    rows = _rows("SELECT t.id, t.requirement_id, t.json, r.text, v.verdict, v.decision FROM test_cases t "
                 "JOIN reviews v ON v.test_case_id = t.id LEFT JOIN requirements r ON t.requirement_id = 'REQ-' || r.id "
                 "WHERE t.status='active' AND (v.decision='approved' OR (v.decision IS NULL AND v.verdict='approve'))")
    groups: dict[str, dict] = {}
    for r in rows:
        g = groups.setdefault(r["requirement_id"] or "?", {"text": _strip_prefix(r["text"] or "")[1], "cases": []})
        g["cases"].append(redact(json.loads(r["json"])))
    lines = []
    for g in groups.values():
        if g["text"].startswith("[Autopilot]"):
            continue
        lines.append(json.dumps({"messages": [{"role": "system", "content": TEST_CASES_SYSTEM},
                                              {"role": "user", "content": g["text"]},
                                              {"role": "assistant", "content": json.dumps({"test_cases": g["cases"]}, ensure_ascii=False)}]},
                                ensure_ascii=False))
    return Response("\n".join(lines), media_type="application/x-ndjson",
                    headers={"Content-Disposition": 'attachment; filename="testpilot_dataset.jsonl"',
                             "X-Examples": str(len(lines))})


# ---------------- Bảo trì ----------------
@maintenance.get("/requirements")
def requirements():
    """Các yêu cầu còn kịch bản hoạt động, phiên bản mới nhất trước."""
    rows = _rows("SELECT r.id, r.text, r.created_at, r.parent_id, COUNT(t.id) n FROM requirements r "
                 "JOIN test_cases t ON t.requirement_id = 'REQ-' || r.id AND t.status='active' "
                 "WHERE r.text NOT LIKE '[Autopilot]%' GROUP BY r.id ORDER BY r.id DESC")
    out = []
    for r in rows:
        url, text = _strip_prefix(r["text"])
        out.append({"id": r["id"], "url": url, "text": text, "created_at": r["created_at"], "parent_id": r["parent_id"],
                    "cases": r["n"], "host": urlparse(url).netloc if url else urlparse(_default_url()).netloc})
    return out


def _req_cases(rid: int) -> tuple[dict, list[TestCase]]:
    row = _rows("SELECT * FROM requirements WHERE id=?", rid)
    if not row:
        raise HTTPException(404, "Không thấy yêu cầu")
    cases = [TestCase.model_validate_json(r["json"]) for r in
             _rows("SELECT json FROM test_cases WHERE requirement_id=? AND status='active'", f"REQ-{rid}")]
    return row[0], cases


class ImpactIn(BaseModel):
    requirement_id: int
    new_text: str = Field(min_length=3)


@maintenance.post("/impact")
def impact(body: ImpactIn):
    """Yêu cầu thay đổi: kịch bản nào cần sửa, kịch bản nào lỗi thời, hành vi nào chưa có kịch bản."""
    row, cases = _req_cases(body.requirement_id)
    _, old = _strip_prefix(row["text"])
    diff = list(unified_diff(old.splitlines(), body.new_text.splitlines(), lineterm="", n=0))[2:]
    try:
        res = ai_client.find_affected_tests(old, body.new_text, [c.model_dump() for c in cases])
    except Exception as e:
        raise HTTPException(502, f"AI lỗi: {e}")
    titles = {c.id: c.title for c in cases}
    for a in res["affected"]:
        a["title"] = titles.get(a["id"], "")
    return {**res, "diff": diff, "total_cases": len(cases), "unchanged": len(cases) - len(res["affected"])}


class ApplyIn(ImpactIn):
    affected: list[dict] = []
    uncovered: list[str] = []


@maintenance.post("/apply")
def apply_impact(body: ApplyIn, request: Request):
    """Áp dụng: tạo phiên bản yêu cầu mới, bỏ kịch bản lỗi thời, AI viết lại kịch bản cần sửa, sinh thêm phần thiếu."""
    from ai.autopilot import fetch_samples, find_openapi
    from ai.json_utils import unwrap_list
    from ai.llm_provider import get_provider
    from ai.prompts import TEST_CASES_SYSTEM, UPDATE_USER
    from ai.review import review_cases
    from ai.test_generator import _prefix_for, _validate_all, generate_test_cases, summarize_openapi
    row, cases = _req_cases(body.requirement_id)
    url, old = _strip_prefix(row["text"])
    url = url or _default_url()
    check_target(url, client_ip(request))
    conn = get_conn()
    new_rid = conn.execute("INSERT INTO requirements(text, parent_id) VALUES (?,?)",
                           (f"[{url}] {body.new_text}", body.requirement_id)).lastrowid
    for tc in cases:      # requirement_id nằm cả ở cột lẫn trong JSON của kịch bản
        tc.requirement_id = f"REQ-{new_rid}"
        conn.execute("UPDATE test_cases SET requirement_id=?, json=? WHERE id=?", (tc.requirement_id, tc.model_dump_json(), tc.id))
    conn.commit()
    conn.close()

    by_id = {c.id: c for c in cases}
    obsolete = [a["id"] for a in body.affected if a.get("action") == "obsolete" and a.get("id") in by_id]
    to_update = [a for a in body.affected if a.get("action") == "update" and a.get("id") in by_id]
    for cid in obsolete:
        _exec("UPDATE test_cases SET status='obsolete' WHERE id=?", cid)

    updated, failed_update, added, warnings = [], [], [], []
    spec = find_openapi(url)
    diff = "\n".join(unified_diff(old.splitlines(), body.new_text.splitlines(), lineterm="", n=1))
    if to_update and not ai_client.USE_MOCK:
        try:
            items = "\n".join(json.dumps({"test_case": by_id[a["id"]].model_dump(exclude_none=True), "why": a.get("reason", "")},
                                         ensure_ascii=False, default=str) for a in to_update[:15])
            ctx = ("API:\n" + summarize_openapi(spec, limit=3000)) if spec else ""
            raw = unwrap_list(get_provider().complete_json(TEST_CASES_SYSTEM, UPDATE_USER.format(
                diff=diff[:3000], new_text=body.new_text[:3000], context=ctx, items=items[:12000])), "test_cases")
            new_cases, _ = _validate_all(raw)
            for n in new_cases:
                if n.id in by_id:
                    n.requirement_id = f"REQ-{new_rid}"
                    n.category = by_id[n.id].category
                    _exec("UPDATE test_cases SET json=?, version=version+1 WHERE id=?", n.model_dump_json(), n.id)
                    updated.append(n.id)
        except Exception as e:
            warnings.append(f"AI chưa viết lại được kịch bản: {e}")
    failed_update = [a["id"] for a in to_update if a["id"] not in updated]

    if body.uncovered and not ai_client.USE_MOCK:
        try:
            focus = body.new_text + "\n\nChỉ viết kịch bản cho các hành vi mới sau:\n" + "\n".join(f"- {u}" for u in body.uncovered[:8])
            fresh = generate_test_cases(focus, openapi_spec=spec, sample_data=fetch_samples(url, spec) if spec else None,
                                        count=min(max(len(body.uncovered), 1), 10), id_prefix=_prefix_for(body.new_text))
            conn = get_conn()
            for tc in fresh:
                tc.requirement_id = f"REQ-{new_rid}"
                conn.execute("INSERT OR REPLACE INTO test_cases(id, requirement_id, json, version, status) VALUES (?,?,?,1,'active')",
                             (tc.id, tc.requirement_id, tc.model_dump_json()))
                added.append(tc.id)
            conn.commit()
            conn.close()
        except Exception as e:
            warnings.append(f"AI chưa sinh được kịch bản mới: {e}")

    current = [TestCase.model_validate_json(r["json"]) for r in
               _rows("SELECT json FROM test_cases WHERE requirement_id=? AND status='active'", f"REQ-{new_rid}")]
    reviews = review_cases(current, spec)
    for cid in failed_update:      # chưa sửa được: phải hiện rõ để người dùng xử lý tay
        if cid in reviews:
            reviews[cid]["issues"].append({"code": "M01", "severity": "high", "step": None,
                                           "message": "Yêu cầu đã đổi nhưng kịch bản này chưa được cập nhật."})
            reviews[cid].update(verdict="needs_fix", score=min(reviews[cid]["score"], 60))
    save_reviews(reviews)
    return {"requirement_id": new_rid, "obsolete": obsolete, "updated": updated, "not_updated": failed_update,
            "added": added, "warnings": warnings}


@maintenance.get("/drift")
def drift(url: str, request: Request):
    """API đổi so với lúc sinh kịch bản: endpoint mới/bị bỏ, kịch bản đang gọi endpoint không còn tồn tại."""
    from ai.autopilot import find_openapi
    from ai.classifier import _path_match
    from ai.test_generator import is_excluded
    check_target(url, client_ip(request))
    spec = find_openapi(url)
    if not spec:
        return {"openapi_found": False}
    host = urlparse(url).netloc
    now = sorted(f"{m.upper()} {p}" for p, ops in spec.get("paths", {}).items() if not is_excluded(p)
                 for m in ops if m.lower() in ("get", "post", "put", "patch", "delete"))
    last = _rows("SELECT endpoints_json, created_at FROM spec_snapshots WHERE host=? ORDER BY id DESC LIMIT 1", host)
    before = json.loads(last[0]["endpoints_json"]) if last else None
    now_pairs = [e.split(" ", 1) for e in now]
    broken = []
    for c in _active_cases(host):
        for i, s in enumerate(c.steps):
            if s.method and s.path:
                path = re.sub(r"\{\{\s*[\w$]+\s*\}\}", "1", s.path).split("?")[0]
                if path.startswith("/__testpilot"):
                    continue
                ok = any(m == s.method.upper() and _path_match(p, path) for m, p in now_pairs)
                if not ok and path.startswith("/api"):
                    broken.append({"id": c.id, "title": c.title, "step": i + 1, "call": f"{s.method} {s.path}"})
    return {"openapi_found": True, "endpoints": len(now), "snapshot_at": last[0]["created_at"] if last else None,
            "added": sorted(set(now) - set(before)) if before is not None else [],
            "removed": sorted(set(before) - set(now)) if before is not None else [], "broken_cases": broken[:50]}


class LocatorIn(BaseModel):
    url: str


@maintenance.post("/locators")
def locators(body: LocatorIn, request: Request):
    """Mở trang bằng trình duyệt: DOM → phần tử → locator đề xuất, độ ổn định, số phần tử khớp."""
    from ai.locators import inspect_page
    check_target(body.url, client_ip(request))
    try:
        return inspect_page(body.url)
    except Exception as e:
        raise HTTPException(502, f"Không mở được trang: {str(e).splitlines()[0][:200]}")


@maintenance.get("/healings")
def healings():
    rows = _rows("SELECT * FROM healing_patches ORDER BY id DESC LIMIT 100")
    return [{**r, "old_target": json.loads(r["old_target"] or "null"), "new_target": json.loads(r["new_target"] or "null")}
            for r in rows]


class HealDecision(BaseModel):
    decision: str = Field(pattern="^(applied|rejected)$")


@maintenance.post("/healings/{pid}")
def heal_decision(pid: int, body: HealDecision):
    """Người duyệt mới ghi locator mới vào kịch bản; từ chối thì giữ nguyên."""
    from backend.models import Target
    rows = _rows("SELECT * FROM healing_patches WHERE id=?", pid)
    if not rows:
        raise HTTPException(404, "Không thấy bản sửa")
    p = rows[0]
    if body.decision == "applied":
        found = _rows("SELECT json FROM test_cases WHERE id=?", p["test_case_id"])
        if not found:
            raise HTTPException(404, "Kịch bản không còn tồn tại")
        tc = TestCase.model_validate_json(found[0]["json"])
        if not 0 <= p["step_idx"] < len(tc.steps):
            raise HTTPException(409, "Kịch bản đã đổi, bước này không còn tồn tại")
        tc.steps[p["step_idx"]].target = Target.model_validate(json.loads(p["new_target"]))
        _exec("UPDATE test_cases SET json=?, version=version+1 WHERE id=?", tc.model_dump_json(), tc.id)
    _exec("UPDATE healing_patches SET status=? WHERE id=?", body.decision, pid)
    return {"ok": True}

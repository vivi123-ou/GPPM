"""Đánh giá A/B: pipeline cũ so với pipeline có skill, agent duyệt và bài học.

Chạy trên Demo Shop đang tắt lỗi, đo cùng một yêu cầu qua API thật. Có gọi AI nên tốn hạn mức.
    python scripts/eval_skills.py --base http://127.0.0.1:8000 --rounds 3 --out docs/eval/ket-qua.json

Cấu hình:
  A  không skill, Lead, Reviewer AI, Verifier, Fixer (tương đương bản trước vòng sơ loại)
  B  đủ: skill, Lead, Reviewer, Verifier, Fixer
  C  như B, thêm bài học rút từ lỗi của B (đã kích hoạt)

Chỉ số:
  chạy đúng   lượt đạt ÷ tổng lượt trên shop không có lỗi cài sẵn. Yêu cầu không mô tả hành vi sai của shop,
              nên phần lớn lượt không đạt ở đây là do kịch bản viết sai.
  điểm duyệt  điểm trung bình của luật tự động, chấm cùng một thang cho cả ba cấu hình
  phát hiện   số lỗi cài sẵn bị bắt được khi bật từng lỗi
"""
import argparse
import json
import statistics
import time
from pathlib import Path

import httpx

REQUIREMENT = """Khách hàng đặt mua điện thoại tại TVT MOBILE.
- Đặt hàng yêu cầu đăng nhập; chưa đăng nhập gọi đặt hàng trả về 401.
- Đặt hàng hợp lệ trả về 201; tổng tiền (total) bằng tổng (đơn giá × số lượng) của các sản phẩm.
- Email không hợp lệ (rỗng, thiếu @, thiếu tên miền) bị từ chối với mã 422.
- Số lượng mỗi sản phẩm từ 1 đến 20; ngoài khoảng này bị từ chối với mã 422.
- Sản phẩm không tồn tại trả về 404. Đặt vượt số lượng tồn kho trả về 409.
- Tra cứu đơn hàng theo mã đơn trả về đúng thông tin đơn."""


def set_skills(c, base, on: bool):
    for s in c.get(f"{base}/api/knowledge/skills").json()["skills"]:
        c.put(f"{base}/api/knowledge/skills/{s['id']}", json={"enabled": on})


def set_lessons(c, base, status: str):
    for lesson in c.get(f"{base}/api/knowledge/lessons").json():
        c.put(f"{base}/api/knowledge/lessons/{lesson['id']}", json={"status": status})


def one(c, base, url, label, *, review, fix):
    t0 = time.time()
    r = c.post(f"{base}/api/ai/generate", json={"text": REQUIREMENT, "url": url, "review": review, "auto_fix": fix,
                                                "lead": review, "verify": fix})
    if r.status_code != 200:
        return {"config": label, "error": r.text[:300]}
    g = r.json()
    gen_s = round(time.time() - t0, 1)
    c.post(f"{base}/api/shop/reset")
    run = c.post(f"{base}/api/ai/run", json={"test_case_ids": g["ids"], "url": url, "classify": False}).json()
    if run["failed"]:
        fails = [x for x in run["results"] if x["status"] == "failed"]
        items = [{k: v for k, v in x.items() if k != "screenshot"} for x in fails]
        for i in range(0, len(items), 6):
            c.post(f"{base}/api/ai/classify", json={"url": url, "items": items[i:i + 6]})
    bench = c.post(f"{base}/api/quality/benchmark", json={"url": url, "ids": g["ids"]}).json()
    scores = [v["score"] for v in g["reviews"].values()]
    agents = {t["agent"]: t for t in g["trace"]}
    crit = g["criteria"]
    return {"config": label, "cases": len(g["ids"]), "runs": run["total"], "passed": run["passed"],
            "correct_pct": round(run["passed"] / run["total"] * 100) if run["total"] else 0,
            "avg_score": round(statistics.mean(scores)) if scores else None,
            "approve_pct": round(sum(v["verdict"] == "approve" for v in g["reviews"].values()) / len(scores) * 100) if scores else None,
            "detected": bench.get("detected"), "seeded": bench.get("seeded"),
            "criteria": f"{sum(bool(x['covered_by']) for x in crit)}/{len(crit)}" if crit else None,
            "fixer": agents.get("fixer", {}).get("summary"), "skills": agents.get("writer", {}).get("skills"),
            "lessons": agents.get("writer", {}).get("lessons"), "model": agents.get("writer", {}).get("model"),
            "gen_seconds": gen_s, "failed": [x["title"] + ": " + x["error_msg"][:90] for x in run["results"] if x["status"] == "failed"][:12]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--out", default="docs/eval/ket-qua.json")
    a = ap.parse_args()
    base, url = a.base.rstrip("/"), a.base.rstrip("/") + "/shop"
    c = httpx.Client(timeout=900)
    rows = []

    def record(row):
        rows.append(row)
        print(json.dumps({k: v for k, v in row.items() if k != "failed"}, ensure_ascii=False), flush=True)
        out = Path(a.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    for _ in range(a.rounds):
        set_lessons(c, base, "disabled")
        set_skills(c, base, False)
        record(one(c, base, url, "A", review=False, fix=False))
        set_skills(c, base, True)
        record(one(c, base, url, "B", review=True, fix=True))
    learned = c.post(f"{base}/api/knowledge/learn", json={"url": url}).json()
    print("learned", learned.get("created"), flush=True)
    set_lessons(c, base, "active")
    for _ in range(a.rounds):
        record(one(c, base, url, "C", review=True, fix=True))
    set_skills(c, base, True)
    set_lessons(c, base, "pending")
    for label in "ABC":
        part = [r for r in rows if r["config"] == label and "error" not in r]
        if part:
            print(label, "n=", len(part), "đúng", round(statistics.mean(r["correct_pct"] for r in part)), "% điểm",
                  round(statistics.mean(r["avg_score"] for r in part)), "phát hiện",
                  [f"{r['detected']}/{r['seeded']}" for r in part], "lỗi", sum(1 for r in rows if r["config"] == label and "error" in r))


if __name__ == "__main__":
    main()

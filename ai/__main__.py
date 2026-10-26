# SPDX-License-Identifier: Apache-2.0
"""Thử nhanh module AI từ dòng lệnh (cần .env có khoá API):

    python -m ai ping
    python -m ai generate "Yêu cầu..." [-o cases.json]   # sinh test case (đọc OpenAPI nếu có DEMO_SHOP_URL)
    python -m ai run cases.json [base_url]               # chạy test API trong file + AI phân loại lỗi
    python -m ai data "Đăng nhập..."                     # sinh test case rồi sinh dữ liệu cho case đầu
    python -m ai heal new.html "Thêm vào giỏ"            # đề xuất locator mới cho nút tên cũ
    python -m ai autopilot http://127.0.0.1:8000/shop
"""

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


def _dump(obj):
    if hasattr(obj, "model_dump"):
        return obj.model_dump(exclude_none=True)
    if isinstance(obj, list):
        return [_dump(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _dump(v) for k, v in obj.items()}
    return obj


def _print(obj):
    print(json.dumps(_dump(obj), ensure_ascii=False, indent=2))


def _pop_opt(args: list[str], flag: str) -> str | None:
    if flag in args:
        i = args.index(flag)
        value = args[i + 1] if i + 1 < len(args) else None
        del args[i:i + 2]
        return value
    return None


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8")   # console Windows mặc định không in được tiếng Việt
    load_dotenv()
    if not argv:
        print(__doc__)
        return 1
    cmd, args = argv[0], list(argv[1:])
    base_url = os.getenv("DEMO_SHOP_URL", "")
    if cmd == "ping":
        from ai.llm_provider import get_provider
        p = get_provider()
        print(f"{p.name}/{p.model}:", p.complete("Trả lời ngắn gọn.", "Nói 'xin chào' bằng tiếng Việt."))
    elif cmd == "generate":
        from ai.autopilot import fetch_samples, find_openapi
        from ai.test_generator import generate_test_cases
        out = _pop_opt(args, "-o")
        spec = find_openapi(base_url) if base_url else None
        cases = generate_test_cases(" ".join(args), openapi_spec=spec,
                                    sample_data=fetch_samples(base_url, spec) if spec else None)
        if out:
            Path(out).write_text(json.dumps(_dump(cases), ensure_ascii=False, indent=2), encoding="utf-8")
            for c in cases:
                print(f"{c.id}  [{c.type}/{c.priority}]  {c.title}")
            print(f"→ đã lưu {len(cases)} test case vào {out}")
        else:
            _print(cases)
    elif cmd == "run":
        return _run_file(Path(args[0]), args[1] if len(args) > 1 else base_url or "http://127.0.0.1:8000")
    elif cmd == "data":
        from ai.data_generator import generate_test_data
        from ai.test_generator import generate_test_cases
        text = " ".join(args)
        tc = generate_test_cases(text)[0]
        _print({"test_case": tc.title, "data_sets": generate_test_data(tc, text)})
    elif cmd == "heal":
        from ai.healing import suggest_locator
        new_html = Path(args[0]).read_text(encoding="utf-8")
        _print(suggest_locator({"action": "click", "target": {"name": args[1]}}, new_html))
    elif cmd == "autopilot":
        from ai.autopilot import autopilot
        _print(autopilot(args[0]))
    else:
        print(__doc__)
        return 1
    return 0


def _run_file(path: Path, base_url: str) -> int:
    from ai.autopilot import find_openapi
    from ai.classifier import classify_failure
    from ai.quick_runner import run_api_test
    from backend.models import TestCase

    cases = [TestCase.model_validate(x) for x in json.loads(path.read_text(encoding="utf-8"))]
    api_paths = list((find_openapi(base_url) or {}).get("paths", {})) or None
    passed = failed = 0
    for tc in cases:
        if tc.type != "api":
            print(f"⏭  {tc.id} {tc.title} (test UI: chạy bằng runner UI của dashboard)")
            continue
        for res in run_api_test(tc, base_url):
            if res["status"] == "passed":
                passed += 1
                print(f"✅ {tc.id} [{res['data_set']}] {tc.title}")
                continue
            failed += 1
            a = classify_failure(tc, res, api_paths=api_paths)
            print(f"❌ {tc.id} [{res['data_set']}] {tc.title}\n   {res['error_msg']}\n"
                  f"   AI: {a['verdict']} ({a['confidence']:.0%}) — {a['explanation']}")
    print(f"\nTổng: {passed} pass, {failed} fail (chạy trên {base_url})")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

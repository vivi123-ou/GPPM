# SPDX-License-Identifier: Apache-2.0
"""Thử nhanh module AI từ dòng lệnh (cần .env có khoá API):

    python -m ai ping
    python -m ai generate "Người dùng đăng nhập bằng email và mật khẩu..."
    python -m ai data "Đăng nhập..."          # sinh test case rồi sinh dữ liệu cho case đầu
    python -m ai heal old.html new.html "Thêm vào giỏ"
    python -m ai autopilot http://localhost:8001
"""

import json
import sys
from pathlib import Path

from dotenv import load_dotenv


def _print(obj):
    data = obj.model_dump(exclude_none=True) if hasattr(obj, "model_dump") else obj
    if isinstance(data, list):
        data = [x.model_dump(exclude_none=True) if hasattr(x, "model_dump") else x for x in data]
    if isinstance(data, dict) and "test_cases" in data:
        data = {**data, "test_cases": [t.model_dump(exclude_none=True) for t in data["test_cases"]]}
    print(json.dumps(data, ensure_ascii=False, indent=2))


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8")   # console Windows mặc định không in được tiếng Việt
    load_dotenv()
    if not argv:
        print(__doc__)
        return 1
    cmd, args = argv[0], argv[1:]
    if cmd == "ping":
        from ai.llm_provider import get_provider
        p = get_provider()
        print(f"{p.name}/{p.model}:", p.complete("Trả lời ngắn gọn.", "Nói 'xin chào' bằng tiếng Việt."))
    elif cmd == "generate":
        from ai.test_generator import generate_test_cases
        _print(generate_test_cases(" ".join(args)))
    elif cmd == "data":
        from ai.data_generator import generate_test_data
        from ai.test_generator import generate_test_cases
        text = " ".join(args)
        tc = generate_test_cases(text)[0]
        _print({"test_case": tc.title, "data_sets": [d.model_dump() for d in generate_test_data(tc, text)]})
    elif cmd == "heal":
        from ai.healing import suggest_locator
        new_html = Path(args[1]).read_text(encoding="utf-8")
        _print(suggest_locator({"action": "click", "target": {"name": args[2]}}, new_html))
    elif cmd == "autopilot":
        from ai.autopilot import autopilot
        _print(autopilot(args[0]))
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

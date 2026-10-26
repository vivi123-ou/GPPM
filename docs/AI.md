# Module AI của TestPilot

Package `ai/` là "bộ não" của TestPilot: viết test case, sinh dữ liệu, sinh bước UI,
phân loại lỗi, self-healing, Autopilot và phân tích ảnh hưởng khi yêu cầu thay đổi.
AI chỉ sinh **các bước dạng JSON** theo schema chung trong `backend/models.py`, không sinh code.

## Cài đặt và cấu hình

```bash
pip install -r requirements.txt
cp .env.example .env      # điền GEMINI_API_KEY hoặc GROQ_API_KEY, đặt USE_MOCK=0
python -m ai ping         # kiểm tra kết nối LLM
python -m ai generate "Người dùng đăng nhập bằng email và mật khẩu. Email rỗng phải trả 400."
pytest                    # test module AI bằng provider giả, không cần khoá
```

| Biến | Ý nghĩa |
|---|---|
| `USE_MOCK` | `1` = trả dữ liệu trong `backend/mocks/`, `0` = gọi AI thật |
| `LLM_PROVIDER` | `gemini` (mặc định), `groq`, `openai` (ChatGPT, trả phí), `ollama` |
| `LLM_MODEL` | Ghi đè model mặc định (`gemini-3.5-flash`, `llama-3.3-70b-versatile`, `qwen2.5:7b`) |
| `GEMINI_API_KEY`, `GROQ_API_KEY`, `OPENAI_API_KEY`, `OLLAMA_URL` | Khoá / địa chỉ của provider |
| `DEMO_SHOP_URL` | Nếu đặt, AI đọc `/openapi.json` của Demo Shop để dùng đúng path API |

Khoá miễn phí: Gemini tại https://aistudio.google.com/apikey, Groq tại https://console.groq.com/keys.
Chạy offline: cài Ollama, `ollama pull qwen2.5:7b`, đặt `LLM_PROVIDER=ollama`.

## Cấu trúc

| File | Chức năng |
|---|---|
| `llm_provider.py` | `LLMProvider` + `GeminiProvider`, `GroqProvider`, `OllamaProvider`; retry khi 429/5xx; JSON mode; tự sửa JSON hỏng |
| `prompts.py` | Toàn bộ prompt và mô tả schema; muốn chỉnh prompt thì sửa ở đây |
| `test_generator.py` | Yêu cầu (+ OpenAPI) → `TestCase`; chuẩn hoá lỗi vặt, kiểm tra placeholder, cho AI tự sửa 1 lần |
| `data_generator.py` | Dữ liệu EP/BVA; AI dùng token `<faker:email>`, `<len:255>`; có luật dự phòng khi AI lỗi |
| `ui_steps.py` | Accessibility tree / HTML → các bước UI |
| `classifier.py` | `app_bug` / `test_broken` / `flaky`; heuristic trước, AI quyết định và giải thích |
| `healing.py` | Locator hỏng + DOM mới → đề xuất target mới (chỉ chọn phần tử có thật trong DOM) |
| `autopilot.py` | URL → tìm OpenAPI + duyệt trang bằng Playwright → sinh test API và UI |
| `impact.py` | Yêu cầu cũ/mới → test bị ảnh hưởng (`update`/`obsolete`) + hành vi chưa có test |
| `dom.py` | Rút DOM thành danh sách phần tử (role, name, testid) để giảm token |

## Giao tiếp với backend (cho Runner/Dashboard)

Backend chỉ gọi qua `backend/ai_client.py`:

```python
ai_client.generate_test_cases(text) -> list[TestCase]
ai_client.generate_test_data(test_case) -> list[DataSet]
ai_client.generate_ui_steps(goal, html_or_aria_snapshot, url="/") -> list[Step]
ai_client.classify_failure(test_case, result: dict) -> {"verdict", "confidence", "explanation", "suggested_fix", "source"}
ai_client.suggest_locator(step, dom_html) -> {"target": {...} | None, "reason", "confidence", "source"}
ai_client.autopilot(url) -> {"app_summary", "openapi_found", "pages", "test_cases"}
ai_client.find_affected_tests(old_text, new_text, test_cases) -> {"affected": [...], "uncovered": [...]}
```

Quy ước Runner cần biết:

- **ID test case** có dạng `TC-<hash 4 ký tự>-01`, khác nhau giữa các yêu cầu (vì `test_cases.id` là PRIMARY KEY).
- **Placeholder** `{{email}}` trong `path`/`body`/`value`/`expect` được thay bằng `data_sets[].values`; mỗi data set là một lần chạy.
  Nếu cả giá trị chỉ là `"{{quantity}}"` thì giữ nguyên kiểu (số vẫn là số).
- **`save`** (trường mới, tuỳ chọn, ở bước API): `{"order_id": "order_id"}` lấy giá trị từ JSON response lưu vào biến;
  bước sau dùng `{{order_id}}`. Đường dẫn lồng nhau dùng dấu chấm: `items.0.id`.
- **`json_contains`**: response phải chứa tập con này (so sánh số không phân biệt int/float).
- Bản cài đặt tham khảo của các quy ước trên: `ai/quick_runner.py`.
- Trong một test case do `generate_test_cases` sinh, mọi data set có cùng `expected`, nên `expect` của bước áp dụng chung.
- Data set từ `generate_test_data` có thể lẫn `accept` và `reject`. Gợi ý cho Runner: với `reject`, coi là pass nếu API trả 4xx.
- **classify_failure**: `result` càng đầy đủ càng tốt. Các khoá AI hiểu: `error_msg`, `steps`/`step_results` (mỗi bước có `status`, `detail`),
  `expected_status`, `actual_status`, `response_body`, `passed_on_retry`, `history` (ví dụ `["passed","failed"]`).
  Ảnh chụp màn hình bị bỏ qua tự động.
- **suggest_locator**: truyền `page.content()` lúc bước fail. Nếu `target` là `None` thì không tạo bản vá. Kết quả chỉ là đề xuất,
  người dùng duyệt ở màn hình self-healing rồi mới ghi vào test case.
- **autopilot** dùng Playwright sync API, nên route FastAPI gọi nó phải là `def` thường, không phải `async def`.

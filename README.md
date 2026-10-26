# TestPilot — AI Test Engineer

![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-API-009688?logo=fastapi&logoColor=white)
![Playwright](https://img.shields.io/badge/Playwright-Browser%20automation-2EAD33?logo=playwright&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-Database-003B57?logo=sqlite&logoColor=white)

TestPilot là ứng dụng hỗ trợ kiểm thử phần mềm theo yêu cầu. Người dùng nhập user story hoặc API spec, tạo test case, chạy kiểm thử API/UI và xem kết quả ngay trên dashboard. Repo cũng có **TVT MOBILE**, một cửa hàng điện thoại mẫu với dữ liệu SQLite và bug flags để thực hành, tích hợp và trình diễn luồng kiểm thử.

> Trạng thái hiện tại: Demo Shop và module AI (Gemini / Groq / OpenAI / Ollama) đã chạy được; AI viết test, sinh dữ liệu, chạy thử test API và phân loại lỗi trên trang **AI Lab** (`/ai.html`). Runner UI (Playwright), lưu kết quả và màn hình duyệt bản vá trên dashboard đang được phát triển. Xem mục [AI Model](#ai-model).

## Tính năng

### TestPilot

- Nhập yêu cầu và tạo test case theo schema chung.
- Lưu yêu cầu và test case bằng SQLite.
- Dashboard hiện hỗ trợ nhập yêu cầu và quản lý test case.
- Runner API/UI và luồng báo cáo đang là phần cần tích hợp tiếp; các module trong `backend/runner/` hiện chưa triển khai.

### TVT MOBILE Demo Shop

- Cửa hàng điện thoại với 8 sản phẩm mẫu, giỏ hàng và thanh toán.
- REST API có tài liệu OpenAPI tự sinh.
- SQLite tự khởi tạo và nạp dữ liệu mẫu ở lần chạy đầu.
- Bug flags có thể bật/tắt để mô phỏng lỗi nghiệp vụ và thay đổi giao diện.
- `data-testid` trên các thành phần chính để hỗ trợ kiểm thử UI.

## Công nghệ

- Python 3.11+
- FastAPI và Pydantic
- SQLite
- Playwright
- HTML, CSS và JavaScript cho dashboard và Demo Shop

## Cấu trúc dự án

```text
backend/
  main.py            # FastAPI app và API TestPilot
  db.py              # Schema SQLite của TestPilot
  models.py          # Schema test case dùng chung
  ai_client.py       # Điểm nối backend ↔ AI (USE_MOCK=1: mock, 0: AI thật)
  ai_routes.py       # API /api/ai/* cho trang AI Lab
  runner/            # Runner API, UI và self-healing
  mocks/             # Dữ liệu mock cho AI
ai/                  # Module AI (xem mục AI Model)
tests/               # Test tự động của module AI (pytest)
docs/AI.md           # Tài liệu kỹ thuật module AI cho cả nhóm
ShopDemo/            # Demo Shop: API, trang bán hàng và tài nguyên
  main.py            # Entry point để chạy riêng Demo Shop
  routes.py          # API shop, SQLite và bug flags
  templates/         # HTML cửa hàng và trang giới thiệu
  static/
    css/shop.css
    js/shop.js
    images/           # Ảnh sản phẩm, logo và banner
frontend/
  index.html         # Dashboard TestPilot
  ai.html            # AI Lab: sinh test, Autopilot, chạy thử + AI phân tích lỗi
README.md
requirements.txt
```

## Yêu cầu

- Python 3.11 trở lên
- pip
- Chromium của Playwright cho runner UI

## Cài đặt và chạy

Tạo môi trường và cài thư viện một lần:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m playwright install chromium
```

### Chạy TestPilot cùng Demo Shop

Từ thư mục gốc repo, chạy:

```powershell
python -m uvicorn backend.main:app --reload
```

Lệnh này khởi động backend TestPilot và gắn Demo Shop vào cùng server. Mở dashboard tại `http://127.0.0.1:8000/` hoặc shop tại `http://127.0.0.1:8000/shop`.

### Chỉ chạy Demo Shop

Nếu chỉ muốn xem shop mà không mở dashboard TestPilot, chạy:

```powershell
python -m uvicorn ShopDemo.main:app --reload --port 8001
```

Mở `http://127.0.0.1:8001/` hoặc `http://127.0.0.1:8001/shop`. Cả hai cách chạy dùng cùng file dữ liệu `demo_shop.db` ở thư mục gốc.

Các địa chỉ chính:

| Trang | Khi chạy backend chung (8000) | Khi chạy shop độc lập (8001) |
| --- | --- | --- |
| TestPilot dashboard | <http://127.0.0.1:8000/> | Không chạy |
| TVT MOBILE Demo Shop | <http://127.0.0.1:8000/shop> | <http://127.0.0.1:8001/shop> |
| Giới thiệu TVT MOBILE | <http://127.0.0.1:8000/shop/about> | <http://127.0.0.1:8001/shop/about> |
| API docs (Swagger UI) | <http://127.0.0.1:8000/docs> | <http://127.0.0.1:8001/docs> |

Không cần cài hoặc cấu hình database riêng. SQLite tạo `testpilot.db` và `demo_shop.db` trong thư mục gốc khi ứng dụng khởi chạy và khởi tạo dữ liệu tương ứng.

## Demo Shop API

| Method | Endpoint | Mô tả |
| --- | --- | --- |
| `GET` | `/api/shop/products` | Danh sách điện thoại, giá và tồn kho |
| `POST` | `/api/shop/checkout` | Tạo đơn hàng và cập nhật tồn kho |
| `GET` | `/api/shop/orders/{order_id}` | Chi tiết đơn hàng |
| `GET` | `/api/shop/bugs` | Xem trạng thái bug flags |
| `PUT` | `/api/shop/bugs/{flag}` | Bật hoặc tắt một bug flag |
| `POST` | `/api/shop/reset` | Reset đơn hàng, tồn kho và bug flags |

Ví dụ tạo đơn hàng:

```json
{
  "customer_name": "Nguyễn Minh Anh",
  "phone": "0901234567",
  "email": "minhanh@example.com",
  "city": "TP. Hồ Chí Minh",
  "address": "12 Nguyễn Huệ, Quận 1",
  "payment_method": "cod",
  "note": "Gọi trước khi giao",
  "items": [{"product_id": "iphone-15", "quantity": 1}]
}
```

Gửi JSON này tới `POST /api/shop/checkout`. API trả mã đơn, tổng tiền và các dòng sản phẩm; dữ liệu đơn hàng được lưu trong SQLite.

## Kịch bản trình diễn bug flags

| Flag | Khi bật |
| --- | --- |
| `wrong_total` | Tổng đơn hàng bị cộng thừa 100.000₫ |
| `allow_empty_email` | Chấp nhận email không hợp lệ |
| `ignore_stock` | Cho đặt vượt tồn kho và bỏ qua trừ kho |
| `ui_v2` | Đổi màu, font và kiểu nút để thử locator/self-healing |

Bật lỗi tổng tiền:

```powershell
Invoke-RestMethod -Method Put `
  -Uri http://127.0.0.1:8000/api/shop/bugs/wrong_total `
  -ContentType 'application/json' `
  -Body '{"enabled":true}'
```

Tắt lỗi và khôi phục dữ liệu demo:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/shop/reset
```

Các locator chính gồm `add-iphone-15`, `cart-button`, `customer-name`, `email`, `address` và `checkout-button`. Ảnh sản phẩm đặt trong `ShopDemo/static/images/`, đặt tên theo mã sản phẩm (ví dụ `iphone-15.jpg`, `galaxy-z-flip6.jpg`, `redmi-note-14-pro.jpg`). Shop tự dùng hình minh họa dự phòng nếu chưa có ảnh tương ứng. Có thể thêm banner ảnh hoặc GIF với tên `banner.gif` và logo shop với tên `logo.png` trong cùng thư mục. CSS và JavaScript nằm ở `ShopDemo/static/css/shop.css` và `ShopDemo/static/js/shop.js`. Có thể xem toàn bộ request/response schema của các API tại `/docs`.

## AI Model

Module `ai/` là "bộ não" của TestPilot. AI chỉ sinh **các bước dạng JSON** theo schema chung (`backend/models.py`), không sinh code; runner đọc JSON đó để chạy.

### AI Model gồm những gì

| Chức năng | File | AI làm gì |
| --- | --- | --- |
| Gọi LLM | `ai/llm_provider.py` | Một interface cho Gemini, Groq, OpenAI (ChatGPT), Ollama; tự thử lại khi lỗi mạng; tự chuyển provider dự phòng khi hết lượt (429) |
| Viết test case | `ai/test_generator.py` | Đọc yêu cầu + OpenAPI + dữ liệu thật của shop → test case JSON. Tự sửa lỗi lặt vặt, kiểm tra schema, cho AI sửa lại nếu sai |
| Sinh dữ liệu test | `ai/data_generator.py` | Phân vùng tương đương + giá trị biên; Faker tạo dữ liệu thật (email, tên, SĐT); có bộ luật dự phòng khi AI lỗi |
| Bước UI | `ai/ui_steps.py`, `ai/dom.py` | Đọc DOM / accessibility tree → các bước `goto`, `click`, `fill`, `assert_text`... |
| Phân loại lỗi | `ai/classifier.py` | Test fail là **lỗi ứng dụng** (`app_bug`), **test hỏng** (`test_broken`) hay **không ổn định** (`flaky`), kèm giải thích tiếng Việt |
| Self-healing | `ai/healing.py` | Locator hỏng → đề xuất locator mới, chỉ chọn phần tử có thật trong DOM mới |
| Autopilot | `ai/autopilot.py` | Chỉ cần URL → tự duyệt trang (Playwright) + đọc OpenAPI → sinh test |
| Ảnh hưởng thay đổi | `ai/impact.py` | So sánh yêu cầu cũ/mới → test nào cần sửa / bỏ, hành vi nào chưa có test |
| Runner thử | `ai/quick_runner.py` | Chạy test API do AI sinh để kiểm chứng (bản tham khảo cho runner chính thức) |
| Prompt | `ai/prompts.py` | Toàn bộ prompt nằm ở đây |

AI không được sinh test cho các API quản trị (`/api/shop/bugs`, `/api/shop/reset`) và API của chính TestPilot, để test không tự bật/tắt bug hay xoá dữ liệu.

### Lấy khoá AI và cấu hình `.env`

Sao chép file mẫu rồi điền khoá **vào `.env`**. `.env` được git bỏ qua; **không** điền khoá vào `.env.example` vì file đó được đưa lên GitHub.

```powershell
copy .env.example .env
notepad .env
```

| Biến | Lấy ở đâu |
| --- | --- |
| `GEMINI_API_KEY` | <https://aistudio.google.com/apikey> → **Create API key** (miễn phí, có giới hạn lượt/ngày) |
| `GROQ_API_KEY` | <https://console.groq.com/keys> → đăng nhập → **Create API Key** (miễn phí, rất nhanh) |
| `OPENAI_API_KEY` | <https://platform.openai.com/api-keys> → **Create new secret key** (trả phí, cần nạp credit) |
| `OLLAMA_URL` | Không phải khoá. Cài Ollama (<https://ollama.com/download>), chạy `ollama pull qwen2.5:7b`; Ollama tự chạy ở `http://localhost:11434` (giá trị mặc định) |

Các biến khác: `USE_MOCK=0` (gọi AI thật; `1` = dùng mock, không cần khoá), `LLM_PROVIDER` (`gemini` / `groq` / `openai` / `ollama`), `LLM_FALLBACK=groq,openai` (provider dự phòng, cái nào chưa có khoá thì tự bỏ qua), `DEMO_SHOP_URL=http://127.0.0.1:8000` (để AI đọc OpenAPI và dữ liệu thật của shop).

### Hướng dẫn 1: Bật web TestPilot + Demo Shop

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m playwright install chromium
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

| Trang | Địa chỉ |
| --- | --- |
| Dashboard TestPilot | <http://127.0.0.1:8000/> |
| **AI Lab** (thử AI) | <http://127.0.0.1:8000/ai.html> |
| Demo Shop | <http://127.0.0.1:8000/shop> |
| Swagger (gồm API `/api/ai/*`) | <http://127.0.0.1:8000/docs> |

Góc phải trên của AI Lab hiển thị provider đang dùng (vd. `AI: gemini / gemini-3.5-flash`). Nếu thấy "Chế độ MOCK" thì `.env` đang để `USE_MOCK=1`.

### Hướng dẫn 2: Thử AI trên web (AI Lab)

1. Mở <http://127.0.0.1:8000/ai.html>.
2. Ô **1**: bấm **Dùng yêu cầu mẫu** (yêu cầu đặt hàng TVT MOBILE) → **Sinh test case**. Khoảng 30 giây sau, test case mới xuất hiện ở ô **3**.
3. Ô **2**: để tất cả bug flag **tắt** → ô **3** bấm **▶ Chạy test API + AI phân tích**. Kết quả ở ô **4**: gần như tất cả pass.
4. Bật `wrong_total` và `allow_empty_email` → chạy lại. Test tổng tiền và email sai định dạng chuyển sang ❌, AI gắn nhãn **Lỗi ứng dụng** và giải thích (vd. "tổng đúng là 37.980.000 nhưng API trả 38.080.000").
5. Tuỳ chọn: **+ dữ liệu** bên cạnh một test để AI sinh thêm dữ liệu biên; **🚀 Autopilot** để AI tự khám phá shop và viết test.
6. Bấm **Reset shop** để tắt bug và khôi phục tồn kho sau khi demo.

Mỗi lần chạy, runner tự reset tồn kho/đơn hàng của shop nhưng giữ nguyên các bug flag đang bật.

### Hướng dẫn 3: Chạy test case từ file (dòng lệnh)

Web phải đang chạy (Hướng dẫn 1) để có Demo Shop.

```powershell
python -m ai ping                                    # kiểm tra kết nối AI
python -m ai generate "Đặt hàng hợp lệ trả 201, total = giá × số lượng. Email sai định dạng trả 422." -o cases.json
python -m ai run cases.json                          # chạy test API trong file + AI phân loại lỗi
```

File `cases.json` có thể mở ra xem/sửa tay rồi chạy lại. Kết quả in ra từng dòng ✅/❌, dòng lỗi kèm nhãn và giải thích của AI. Các lệnh khác: `python -m ai data "..."`, `python -m ai autopilot http://127.0.0.1:8000/shop`.

Test tự động của module AI (không cần khoá, dùng AI giả lập):

```powershell
pytest
```

### Kết quả thử nghiệm thực tế

Chạy trên Demo Shop với Gemini (`gemini-3.5-flash`), yêu cầu đặt hàng ở trên; AI sinh 7 test case / 11 lượt chạy (tính cả data set):

| Tình huống | Kết quả | AI phân loại |
| --- | --- | --- |
| Tắt hết bug | 10 pass, 1 fail | Case fail: AI đoán response có trường `id` nhưng shop trả `order_id` → **Test hỏng** (đúng) |
| Bật `wrong_total` | 2 test kiểm tra tổng tiền fail | **Lỗi ứng dụng**: "tổng đúng 52.970.000 nhưng API trả 53.070.000" (đúng) |
| Bật `allow_empty_email` | 2 data set email sai định dạng fail (shop trả 201 thay vì 422) | **Lỗi ứng dụng** (đúng) |
| Test mock cũ gọi `/api/login` (không tồn tại) | fail 405 | **Test hỏng**: API không có trong OpenAPI (đúng) |

### API của AI (cho dashboard)

| Method | Endpoint | Mô tả |
| --- | --- | --- |
| `GET` | `/api/ai/config` | Provider/model đang dùng |
| `POST` | `/api/ai/run` | Chạy test API (`{"test_case_ids": [...]}` hoặc tất cả) + AI phân loại lỗi |
| `POST` | `/api/ai/autopilot` | `{"url": "..."}` → AI khám phá và sinh test (mặc định lưu vào danh sách) |
| `POST` | `/api/ai/test-data/{id}?save=true` | Sinh dữ liệu EP/BVA cho một test case |
| `POST` | `/api/ai/heal` | `{"step": {...}, "url": "..."}` → đề xuất locator mới |
| `POST` | `/api/ai/impact` | `{"old_text", "new_text"}` → test bị ảnh hưởng |

Quy ước cho runner (thay biến `{{x}}`, `save`, `json_contains`, data set `accept`/`reject`) xem [docs/AI.md](docs/AI.md).

### Lưu ý

- Gói miễn phí của Gemini giới hạn lượt gọi mỗi ngày; khi hết sẽ báo `429`. Điền thêm `GROQ_API_KEY` để AI tự chuyển sang Groq.
- Một số model Gemini mới (3.7, 3.8, `flash-latest`) có lúc không phản hồi; `gemini-3.5-flash` ổn định. Đổi bằng `LLM_MODEL`.
- Trên Windows dùng `127.0.0.1` thay vì `localhost` (mỗi request qua `localhost` chậm thêm khoảng 2 giây).

## Ghi chú dữ liệu

- `demo_shop.db` chứa sản phẩm, đơn hàng và trạng thái bug flags của cửa hàng mẫu.
- `testpilot.db` chứa dữ liệu TestPilot như yêu cầu, test case, lượt chạy và kết quả.
- Dữ liệu SQLite được tạo tại máy chạy ứng dụng, không cần commit các file database vào Git.

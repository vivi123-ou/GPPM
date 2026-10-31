# TestPilot — AI Test Engineer

![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-API-009688?logo=fastapi&logoColor=white)
![Playwright](https://img.shields.io/badge/Playwright-Browser%20automation-2EAD33?logo=playwright&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-Database-003B57?logo=sqlite&logoColor=white)

TestPilot là ứng dụng hỗ trợ kiểm thử phần mềm theo yêu cầu. Người dùng nhập user story hoặc API spec, tạo test case, chạy kiểm thử API/UI và xem kết quả ngay trên dashboard. Repo cũng có **TVT MOBILE**, một cửa hàng điện thoại mẫu với dữ liệu SQLite và bug flags để thực hành, tích hợp và trình diễn luồng kiểm thử.

> **Tài liệu kỹ thuật đầy đủ:** đọc thư mục [docs/handbook](docs/handbook). API tương tác ở `/docs`.

## Tính năng

### TestPilot

- **Sinh kịch bản** chức năng, bảo mật (OWASP) và hiệu năng từ yêu cầu hoặc từ một URL (Autopilot).
- **Pipeline agent**: Writer viết, Reviewer chấm điểm bằng 17 luật và đối chiếu tiêu chí chấp nhận, Fixer tự sửa. Mọi lượt đều ghi vết.
- **Skill và bài học**: kiến thức QA đọc và sửa được; hệ thống rút bài học từ kết quả thật, người duyệt mới có hiệu lực. Xuất dữ liệu JSONL để fine-tune sau này.
- **Thực thi đúng kịch bản đã chọn**, API bằng HTTP và UI bằng Playwright; phân loại nguyên nhân lỗi; báo cáo Excel kèm các bước tái hiện.
- **Self-healing locator** có người duyệt; phân tích DOM và độ bền của locator.
- **Bảo trì**: phân tích ảnh hưởng khi yêu cầu đổi, phát hiện API đổi, lịch sử phiên bản.
- **Số liệu đo được**: tỉ lệ sinh đúng định dạng, qua duyệt, độ phủ, phát hiện lỗi cài sẵn.
- **Bảo mật của chính ứng dụng**: không lưu mật khẩu tài khoản thử nghiệm, chặn SSRF, token API, giới hạn tần suất, header bảo mật.

### TVT MOBILE Demo Shop

- Cửa hàng điện thoại với 8 sản phẩm mẫu, giỏ hàng và thanh toán.
- Đăng ký, đăng nhập email/mật khẩu và tài khoản demo được seed từ `.env`.
- Checkout yêu cầu đăng nhập; mật khẩu lưu dưới dạng PBKDF2 hash và session dùng cookie HttpOnly.
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
  ai_routes.py       # API /api/ai/* cho trang Kiểm thử website
  export.py          # Xuất Excel/CSV test case và báo cáo
  quality_routes.py  # API số liệu, duyệt, skill, bài học, bảo trì
  security.py        # Token, giới hạn tần suất, header bảo mật, chặn SSRF
  vault.py           # Tài khoản thử nghiệm, chỉ nằm trong bộ nhớ
  demo_pack.py       # Bộ kịch bản mẫu viết tay, không cần AI
  mocks/             # Dữ liệu mock cho AI
ai/                  # Module AI (xem mục AI Model)
tests/               # Test tự động của module AI (pytest)
docs/handbook/       # Tài liệu kỹ thuật
docs/AI.md           # Quy ước module AI cho cả nhóm
scripts/             # Đánh giá A/B, khởi động buổi demo
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
  ai.html            # Kiểm thử website: tạo kịch bản, tự động khám phá, thực thi, báo cáo
  vendor/            # Tailwind, Alpine, marked lưu sẵn: chạy được khi không có Internet
  theme.css, theme.js # Giao diện dùng chung, thanh điều hướng
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

Nếu muốn tạo tài khoản demo có sẵn, sao chép `.env.example` thành `.env`, rồi điền `SHOP_DEMO_EMAIL` và `SHOP_DEMO_PASSWORD` trong `.env`. Không commit `.env` hoặc chia sẻ mật khẩu này.

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
| Đăng nhập | <http://127.0.0.1:8000/shop/login> | <http://127.0.0.1:8001/shop/login> |
| Đăng ký | <http://127.0.0.1:8000/shop/register> | <http://127.0.0.1:8001/shop/register> |
| API docs (Swagger UI) | <http://127.0.0.1:8000/docs> | <http://127.0.0.1:8001/docs> |

Không cần cài hoặc cấu hình database riêng. SQLite tạo `testpilot.db` và `demo_shop.db` trong thư mục gốc khi ứng dụng khởi chạy và khởi tạo dữ liệu tương ứng.

## Demo Shop API

| Method | Endpoint | Mô tả |
| --- | --- | --- |
| `GET` | `/api/shop/products` | Danh sách điện thoại, giá và tồn kho |
| `POST` | `/api/shop/auth/register` | Đăng ký tài khoản và tạo phiên đăng nhập |
| `POST` | `/api/shop/auth/login` | Đăng nhập bằng email và mật khẩu |
| `GET` | `/api/shop/auth/me` | Thông tin tài khoản đang đăng nhập |
| `POST` | `/api/shop/auth/logout` | Đăng xuất và xóa phiên |
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

Gửi JSON này tới `POST /api/shop/checkout` sau khi đăng nhập để có session cookie. API trả mã đơn, tổng tiền và các dòng sản phẩm; dữ liệu đơn hàng được lưu trong SQLite.

## Kịch bản trình diễn bug flags

| Flag | Khi bật |
| --- | --- |
| `wrong_total` | Tổng đơn hàng bị cộng thừa 100.000₫ |
| `allow_empty_email` | Chấp nhận email không hợp lệ |
| `ignore_stock` | Cho đặt vượt tồn kho và bỏ qua trừ kho |
| `ui_v2` | Đổi giao diện, đổi `data-testid` và chữ trên nút, làm gãy locator cũ để thử self-healing |

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
| **Kiểm thử website** | <http://127.0.0.1:8000/ai.html> |
| Demo Shop | <http://127.0.0.1:8000/shop> |
| Swagger (gồm API `/api/ai/*`) | <http://127.0.0.1:8000/docs> |

Góc phải trên thanh điều hướng hiển thị provider đang dùng (vd. `AI: gemini / gemini-3.5-flash`). Nếu thấy "Chế độ MOCK" thì `.env` đang để `USE_MOCK=1`.

### Số lượng kịch bản (tới 100+)

Ô **Số lượng** cạnh nút *Tạo kịch bản* cho phép chọn tự động (4–10), 20, 50 hoặc 100 kịch bản (API tối đa 150).
Với số lượng lớn, TestPilot làm hai bước: AI **lập kế hoạch** danh sách kịch bản (luồng chính, từng quy tắc kiểm tra dữ liệu,
giá trị biên, quy tắc nghiệp vụ, trường hợp không tồn tại/xung đột, dữ liệu bất thường), sau đó **viết chi tiết theo đợt 10 kịch bản**,
chạy song song (`AI_PARALLEL`, mặc định 3). Đợt nào lỗi không làm hỏng cả lượt; kịch bản trùng tiêu đề bị loại.

Hạn mức gói miễn phí ảnh hưởng tới tốc độ: Groq giới hạn **8.000 token/phút cho mỗi model**, nên TestPilot xoay vòng giữa
3 model Groq (`LLM_FALLBACK`) và chỉ chờ khi mọi model đều đang bị giới hạn. Gemini miễn phí có hạn mức theo ngày; khi hết,
Gemini được tạm bỏ qua 10 phút (`LLM_COOLDOWN`) thay vì thử lại ở mỗi lần gọi.

### Hướng dẫn 2: Thử AI trên web (trang Kiểm thử website)

1. Mở <http://127.0.0.1:8000/ai.html>. Bước **1 · Hệ thống mục tiêu** đã điền sẵn Demo Shop; bấm **Kiểm tra** để xem trạng thái kết nối, tài liệu OpenAPI và phương pháp đề xuất.
2. Bước **2 · Tạo kịch bản**, tab *Từ yêu cầu nghiệp vụ*: bấm **Chèn yêu cầu mẫu**, chọn số lượng, bấm **Tạo kịch bản**.
3. Mục **Mô phỏng lỗi**: để tất cả tắt → bước **3 · Thực thi** bấm **Thực thi**. Kết quả ở bước **4 · Báo cáo kết quả**: gần như tất cả *Đạt*.
4. Bật *Sai tổng tiền* (`wrong_total`) và *Bỏ kiểm tra email* (`allow_empty_email`) → thực thi lại. Kịch bản tổng tiền và email sai định dạng chuyển sang *Không đạt*, được phân loại **Lỗi ứng dụng** kèm giải thích (ví dụ: "tổng đúng là 37.980.000 nhưng API trả 38.080.000").
5. Tuỳ chọn: **Bổ sung dữ liệu** cạnh một kịch bản để thêm dữ liệu biên; tab *Tự động khám phá* để TestPilot tự khảo sát website.
6. Bấm **Khôi phục mặc định** để tắt lỗi mô phỏng và khôi phục tồn kho.

Mỗi lần chạy, runner tự reset tồn kho/đơn hàng của shop nhưng giữ nguyên các bug flag đang bật.

### AI đang dùng model nào?

- **Provider chính** là `LLM_PROVIDER` trong `.env` (mặc định `gemini` → `gemini-3.5-flash`).
- **Dự phòng** theo thứ tự `LLM_FALLBACK` (mặc định `groq` → `openai/gpt-oss-120b`, rồi `openai` → `gpt-5-mini`): khi provider chính lỗi hoặc hết lượt (429), AI tự chuyển sang cái tiếp theo. Provider nào chưa có khoá thì bỏ qua.
- **Ollama** chỉ dùng khi đặt `LLM_PROVIDER=ollama`.
- Góc phải trên thanh điều hướng hiển thị provider chính, danh sách dự phòng và provider **vừa dùng** thực tế.

### Hướng dẫn 2b: Test website khác

Bước **1 · Hệ thống mục tiêu** nhận URL bất kỳ (trang web hoặc link `openapi.json`). Bấm **Kiểm tra**: TestPilot báo website có truy cập được không, có tài liệu OpenAPI không (bao nhiêu endpoint) và **đề xuất phương pháp** — *Từ yêu cầu nghiệp vụ* nếu có OpenAPI, *Tự động khám phá* nếu chỉ có giao diện. Danh sách kịch bản ở bước 3 mặc định chỉ hiển thị kịch bản của hệ thống đang chọn. Các hệ thống mẫu:

| Website | Loại | Cách thử |
| --- | --- | --- |
| Demo Shop (TVT MOBILE) | API + UI, có bug flags | Sinh test từ yêu cầu mẫu hoặc Autopilot, rồi chạy |
| Swagger Petstore (`https://petstore3.swagger.io/api/v3/openapi.json`) | API công khai | **Chèn yêu cầu mẫu** → **Tạo kịch bản** → **Thực thi** |
| Sauce Demo (`https://www.saucedemo.com`) | Chỉ giao diện | Tab **Tự động khám phá** → **Bắt đầu khám phá** |

- Website có OpenAPI (AI tự dò `/openapi.json`, `/api/v3/openapi.json`, `/swagger.json`..., hoặc dán thẳng link file `.json`): AI dùng đúng đường dẫn API và dữ liệu thật, test API **chạy được ngay** và được AI phân loại lỗi.
- Website chỉ có giao diện: Autopilot sinh test **UI** và chạy bằng Playwright.
- Website cần đăng nhập: cung cấp tài khoản thử nghiệm để Autopilot khám phá phần bên trong.

Kết quả thử thật: Petstore 4 test (3 pass, 1 fail: tạo thú cưng hợp lệ nhưng server trả 500, AI phân loại **Lỗi ứng dụng**, kiểm tra tay xác nhận đúng); Sauce Demo: Autopilot sinh 7 test UI cho luồng đăng nhập.

### Xuất tài liệu cho dev (Excel / CSV / JSON)

| Ở đâu | Nút | File nhận được |
| --- | --- | --- |
| Trang Tổng quan (`/`) | **Xuất tài liệu ▾** → Excel / CSV / JSON | Test case đang hiển thị (theo ô tìm kiếm và bộ lọc) |
| Kiểm thử website, bước 3 | **Xuất Excel** | Kịch bản đã chọn (hoặc toàn bộ của hệ thống đang chọn) |
| Kiểm thử website, bước 4 | **Xuất báo cáo (Excel)** / **JSON** | Báo cáo lần thực thi gần nhất |

File Excel test case gồm 4 sheet: **Tổng quan** (số lượng theo loại / ưu tiên, model AI), **Test cases** (mỗi bước một dòng: hành động, đối tượng, dữ liệu, kết quả mong đợi), **Dữ liệu test** (bộ dữ liệu hợp lệ / không hợp lệ, tô màu), **Yêu cầu** (yêu cầu gốc). Báo cáo kết quả gồm tỉ lệ pass, số lỗi theo nhãn AI và từng lượt chạy kèm giải thích, đề xuất sửa. CSV có BOM để Excel mở đúng tiếng Việt.

### Tự động toàn bộ cho website bất kỳ

Trang **Kiểm thử** → nhập URL → **Kiểm tra** → tab *Tự động khám phá* → **Tự động toàn bộ →**:
TestPilot mở website bằng trình duyệt, khảo sát các trang, tạo kịch bản (UI, kèm API nếu có OpenAPI),
**thực thi** (API bằng HTTP, giao diện bằng Playwright), phân loại nguyên nhân lỗi và **tự tải báo cáo Excel**.

- **Website cần đăng nhập**: tích *Website yêu cầu đăng nhập* và nhập tài khoản thử nghiệm. TestPilot đăng nhập trước
  rồi khảo sát các trang bên trong. Mật khẩu **không gửi cho AI, không ghi vào kịch bản hay DB**: kịch bản chỉ giữ dấu
  `__USERNAME__`/`__PASSWORD__`, giá trị thật nằm trong bộ nhớ server và chỉ dùng khi thực thi. Khởi động lại server thì nhập lại.
- **Kịch bản giao diện**: mỗi lượt không đạt có ảnh chụp màn hình và nhật ký từng bước.
- **Self-healing**: khi không tìm thấy phần tử, TestPilot gửi DOM hiện tại cho AI đề xuất locator thay thế, chạy thử ngay;
  nếu thành công, báo cáo hiện bản sửa kèm nút **Áp dụng** (ghi vào kịch bản, tăng phiên bản).
- Tự nhận diện OpenAPI/Swagger ở các đường dẫn phổ biến (`/openapi.json`, `/swagger/v1/swagger.json`, `/v3/api-docs`, …).

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
| `GET` | `/api/ai/inspect?url=...` | Kiểm tra hệ thống: kết nối, OpenAPI, số endpoint, phương pháp đề xuất |
| `POST` | `/api/ai/generate` | `{"text", "url", "count", "categories"}` → pipeline agent (count tối đa 150) |
| `POST` | `/api/ai/run` | `{"test_case_ids": [...], "url"}` → chạy đúng các kịch bản đã chọn; danh sách rỗng là lỗi 400 |
| `POST` | `/api/ai/autopilot` | `{"url", "username"?, "password"?}` → khảo sát website (đăng nhập nếu có tài khoản) và tạo kịch bản |
| `POST` | `/api/ai/test-data/{id}?save=true` | Sinh dữ liệu EP/BVA cho một test case |
| `POST` | `/api/ai/heal` | `{"step": {...}, "url": "..."}` → đề xuất locator mới |
| `POST` | `/api/ai/heal/apply` | `{"test_case_id", "step_idx", "new_target"}` → áp dụng bản sửa locator |
| `POST` | `/api/ai/classify` | `{"items": [...], "url"}` → phân loại nguyên nhân (theo lô) |
| `POST` | `/api/ai/impact` | `{"old_text", "new_text"}` → test bị ảnh hưởng |
| `GET` | `/api/export/test-cases.xlsx?ids=...` | Tài liệu test case (Excel) |
| `GET` | `/api/export/test-cases.csv?ids=...` | Test case dạng CSV |
| `POST` | `/api/export/report.xlsx` | Gửi JSON kết quả của `/api/ai/run` → báo cáo Excel |

Danh sách đầy đủ, gồm `/api/quality`, `/api/knowledge`, `/api/maintenance`, xem [tham chiếu API](docs/handbook/09-api.md).

Quy ước cho runner (thay biến `{{x}}`, `save`, `json_contains`, data set `accept`/`reject`) xem [docs/AI.md](docs/AI.md).

### Lưu ý

- Gói miễn phí của Gemini giới hạn lượt gọi mỗi ngày; khi hết sẽ báo `429`. Điền thêm `GROQ_API_KEY` để AI tự chuyển sang Groq.
- Một số model Gemini mới (3.7, 3.8, `flash-latest`) có lúc không phản hồi; `gemini-3.5-flash` ổn định. Đổi bằng `LLM_MODEL`.
- Trên Windows dùng `127.0.0.1` thay vì `localhost` (mỗi request qua `localhost` chậm thêm khoảng 2 giây).

## Ghi chú dữ liệu

- `demo_shop.db` chứa sản phẩm, đơn hàng và trạng thái bug flags của cửa hàng mẫu.
- `testpilot.db` chứa dữ liệu TestPilot như yêu cầu, test case, lượt chạy và kết quả.
- Dữ liệu SQLite được tạo tại máy chạy ứng dụng, **không commit** các file database vào Git (`testpilot.db` có thể chứa dữ liệu kiểm thử của các website đã thử).

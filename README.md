# TestPilot — AI Test Engineer

![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-API-009688?logo=fastapi&logoColor=white)
![Playwright](https://img.shields.io/badge/Playwright-Browser%20automation-2EAD33?logo=playwright&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-Database-003B57?logo=sqlite&logoColor=white)

TestPilot là ứng dụng hỗ trợ kiểm thử phần mềm theo yêu cầu. Người dùng nhập user story hoặc API spec, tạo test case, chạy kiểm thử API/UI và xem kết quả ngay trên dashboard. Repo cũng có **TVT MOBILE**, một cửa hàng điện thoại mẫu với dữ liệu SQLite và bug flags để thực hành, tích hợp và trình diễn luồng kiểm thử.

> Trạng thái hiện tại: khung dashboard, runner và Demo Shop đang được phát triển. Phần sinh test hiện dùng dữ liệu mock mặc định; kết nối LLM thật chưa được tích hợp.

## Tính năng

### TestPilot

- Nhập yêu cầu và tạo test case theo schema chung.
- Lưu yêu cầu và test case bằng SQLite.
- Dashboard hiện hỗ trợ nhập yêu cầu và quản lý test case.
- Runner API/UI và luồng báo cáo đang là phần cần tích hợp tiếp; các module trong `backend/runner/` hiện chưa triển khai.

### TVT MOBILE Demo Shop

- Cửa hàng điện thoại với danh sách sản phẩm, giỏ hàng và thanh toán.
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
  ai_client.py       # Bộ sinh mock hiện tại; điểm nối cho AI provider
  runner/            # Runner API, UI và self-healing
  mocks/             # Dữ liệu mock cho AI
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

Các locator chính gồm `add-iphone-15`, `cart-button`, `customer-name`, `email`, `address` và `checkout-button`. Ảnh sản phẩm đặt trong `ShopDemo/static/images/`, đặt tên theo mã sản phẩm (ví dụ `iphone-15.jpg`, `galaxy-s24.jpg`). Shop tự dùng hình minh họa dự phòng nếu chưa có ảnh tương ứng. Có thể thêm banner ảnh hoặc GIF với tên `banner.gif` và logo shop với tên `logo.png` trong cùng thư mục. CSS và JavaScript nằm ở `ShopDemo/static/css/shop.css` và `ShopDemo/static/js/shop.js`. Có thể xem toàn bộ request/response schema của các API tại `/docs`.

## AI hiện tại

Mặc định `USE_MOCK=1`, vì vậy luồng tạo test case và các hàm AI đang đọc dữ liệu trong `backend/mocks/`. Khi đặt `USE_MOCK=0`, provider thật chưa được nối và các hàm sẽ báo chưa triển khai. Không cần API key để chạy bản demo hiện tại.

## Ghi chú dữ liệu

- `demo_shop.db` chứa sản phẩm, đơn hàng và trạng thái bug flags của cửa hàng mẫu.
- `testpilot.db` chứa dữ liệu TestPilot như yêu cầu, test case, lượt chạy và kết quả.
- Dữ liệu SQLite được tạo tại máy chạy ứng dụng, không cần commit các file database vào Git.

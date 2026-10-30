# Bảo mật

Tài liệu gồm hai phần: bảo vệ chính TestPilot, và khả năng kiểm thử bảo mật của hệ thống khác.

## Bảo vệ TestPilot

| Rủi ro | Biện pháp | Ở đâu |
| --- | --- | --- |
| Lộ mật khẩu tài khoản thử nghiệm | Không lưu vào SQLite, không gửi cho AI; chỉ giữ trong bộ nhớ. Kịch bản lưu dấu `__USERNAME__`, `__PASSWORD__`. Dữ liệu cũ được tự động làm sạch khi khởi động | `backend/vault.py`, `backend/db.py` |
| Lộ bí mật trong báo cáo | Che các trường pass, token, secret ở kết quả chạy, bước tái hiện, curl, Excel, CSV | `redact`, `_mask` |
| SSRF (lợi dụng server gọi vào mạng nội bộ) | Chỉ nhận http, https. Luôn chặn metadata cloud và link-local, kể cả khi bị chuyển hướng. Địa chỉ nội bộ chỉ cho người dùng trên chính máy chủ | `backend/security.py`, `ai/http.py` |
| XSS từ nội dung website qua AI | Thoát HTML khi hiển thị; Content-Security-Policy | `frontend/ai.html`, `security.py` |
| Prompt injection trong trang web | Coi nội dung là dữ liệu không đáng tin, AI chỉ trả JSON theo schema, kiểm tra schema, chỉ chọn phần tử có thật | `ai/prompts.py`, `ai/test_generator.py` |
| Kịch bản AI dẫn trình duyệt ra ngoài | `goto` ngoài hệ thống đích bị từ chối | `ai/ui_runner.py` |
| Đầu độc kiến thức của AI | Bài học phải được người duyệt | `backend/quality_routes.py` |
| Công thức độc trong Excel | Vô hiệu hoá ô bắt đầu bằng `=`, `+`, `-`, `@` | `backend/export.py` |
| Lạm dụng hạn mức AI | Giới hạn tần suất theo IP, giới hạn dung lượng request | `security.py` |
| Truy cập trái phép API | Token tuỳ chọn `TESTPILOT_TOKEN` | `security.py` |
| Bị nhúng vào website khác | `X-Frame-Options`, `frame-ancestors` | `security.py` |

## Cấu hình khi triển khai

| Biến | Ý nghĩa |
| --- | --- |
| `TESTPILOT_TOKEN` | Đặt giá trị để yêu cầu token cho mọi API của TestPilot |
| `ALLOW_PRIVATE_TARGETS` | `local` (mặc định), `1` hoặc `0` |
| `AI_RATE_LIMIT` | Số lượt gọi AI, thực thi mỗi phút cho mỗi IP, mặc định 60 |
| `COOKIE_SECURE` | Đặt `1` khi chạy HTTPS để cookie của Demo Shop có cờ Secure |

Mặc định server chỉ nên lắng nghe ở `127.0.0.1`. Khi mở ra mạng, hãy đặt `TESTPILOT_TOKEN` và chạy sau HTTPS.

## Giới hạn đã biết

- CSP phải cho phép `unsafe-inline` và `unsafe-eval` vì giao diện dùng Alpine.js và Tailwind ở chế độ chạy trực tiếp. Bản sản xuất nên biên dịch sẵn CSS và dùng bản Alpine tương thích CSP.
- Kiểm tra SSRF phân giải DNS trước khi gọi, chưa chống được hoàn toàn kỹ thuật DNS rebinding.
- Giới hạn tần suất nằm trong bộ nhớ của một tiến trình.
- Chưa có phân quyền nhiều người dùng; token là dùng chung.
- API quản trị của Demo Shop (`/api/shop/bugs`, `/api/shop/reset`) cố tình không có xác thực vì đây là hệ thống mẫu để trình diễn.

## Kiểm thử bảo mật hệ thống khác

Tick nhóm **Bảo mật** khi tạo kịch bản. Agent Security sinh hai loại:

**Dò theo OpenAPI, không cần AI**

| OWASP | Kiểm tra |
| --- | --- |
| A01 Kiểm soát truy cập | API nhạy cảm từ chối người chưa đăng nhập; đọc dữ liệu của người khác qua ID (IDOR) |
| A03 Injection | Chuỗi SQL và mã script không gây lỗi máy chủ, không lộ lỗi nội bộ, không phản chiếu vào HTML |
| A04 Thiết kế không an toàn | Dữ liệu rất dài, sai kiểu không gây lỗi máy chủ |
| A05 Cấu hình sai | Có header bảo mật; trang lỗi không lộ thông tin nội bộ |
| A07 Lỗi xác thực | Giới hạn số lần đăng nhập sai; cookie có HttpOnly và SameSite |

**Logic nghiệp vụ, do AI viết**: sửa giá phía client, gửi thêm trường không được phép, thao tác sai thứ tự.

## Nguyên tắc đạo đức và giới hạn an toàn

- Chỉ kiểm thử hệ thống bạn có quyền. Website bên ngoài phải xác nhận trước khi tạo và chạy kịch bản bảo mật, hiệu năng hoặc thao tác ghi/xoá.
- Payload chỉ để chứng minh điểm yếu, không phá dữ liệu, không khai thác sâu.
- Số request có giới hạn: 100 request, 10 luồng với hệ thống cục bộ; 20 request, 3 luồng với website bên ngoài.
- Kết quả đạt không có nghĩa là hệ thống an toàn tuyệt đối; đây là lớp kiểm tra tự động cơ bản.

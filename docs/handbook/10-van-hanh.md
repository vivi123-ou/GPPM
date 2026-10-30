# Cài đặt và xử lý sự cố

## Cài đặt

Yêu cầu Python 3.11 trở lên.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m playwright install chromium
copy .env.example .env
notepad .env
```

Điền ít nhất một khoá AI. Không điền khoá vào `.env.example`.

| Biến | Lấy ở đâu |
| --- | --- |
| `GEMINI_API_KEY` | <https://aistudio.google.com/apikey> |
| `GROQ_API_KEY` | <https://console.groq.com/keys> |
| `OPENAI_API_KEY` | <https://platform.openai.com/api-keys> (trả phí) |
| `OLLAMA_URL` | Cài Ollama để chạy không cần mạng |

## Chạy

```powershell
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Mở <http://127.0.0.1:8000/>. Trên Windows dùng `127.0.0.1`, không dùng `localhost` (chậm khoảng 2 giây mỗi request). Sửa `.env` xong phải khởi động lại server.

Dùng DB riêng cho từng mục đích bằng biến môi trường:

```powershell
$env:TESTPILOT_DB = "demo.db"; python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

## Kiểm tra sau khi cài

```powershell
pytest                # toàn bộ test tự động, không cần khoá AI
python -m ai ping     # kiểm tra kết nối AI
```

## Xử lý sự cố

| Hiện tượng | Nguyên nhân thường gặp | Cách xử lý |
| --- | --- | --- |
| Góc trên báo "Chế độ mock" | `USE_MOCK=1` | Đặt `USE_MOCK=0`, khởi động lại |
| Sinh rất chậm | Hết hạn mức, đang chuyển sang model dự phòng | Chờ, giảm số lượng, hoặc thêm khoá dự phòng |
| `AI lỗi: ... 429` | Mọi provider đều hết hạn mức | Dùng khoá khác, hoặc **Nạp bộ kịch bản mẫu** |
| Tất cả kịch bản Demo Shop trả 401 | Kịch bản cũ, viết trước khi shop yêu cầu đăng nhập | Sinh lại kịch bản |
| "Kịch bản cần tài khoản thử nghiệm" | Server vừa khởi động lại, tài khoản chỉ nằm trong bộ nhớ | Nhập lại tài khoản rồi thực thi |
| 403 khi tạo kịch bản bảo mật | Website bên ngoài chưa xác nhận quyền | Tick xác nhận nếu bạn thực sự có quyền |
| 403 với địa chỉ nội bộ | Gọi từ máy khác | Xem `ALLOW_PRIVATE_TARGETS` |
| 429 từ TestPilot | Vượt `AI_RATE_LIMIT` | Chờ một phút hoặc tăng giới hạn |
| Lỗi `Executable doesn't exist` | Chưa cài trình duyệt | `python -m playwright install chromium` |
| Khung xem trước trống | Website cấm nhúng khung | Bấm mở tab mới |

## Dữ liệu

- `testpilot.db`: yêu cầu, kịch bản, kết quả, skill, bài học.
- `demo_shop.db`: dữ liệu Demo Shop.
- Cả hai được tạo tự động và không nên đưa lên git.

Sao lưu bằng cách chép file khi server đang dừng.

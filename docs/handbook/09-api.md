# Tham chiếu API và schema

Tài liệu tương tác đầy đủ ở [Swagger](/docs). Dưới đây là các API chính.

## Sinh và thực thi

| Method | Endpoint | Mô tả |
| --- | --- | --- |
| `GET` | `/api/ai/config` | Provider và model đang dùng |
| `GET` | `/api/ai/inspect?url=` | Kiểm tra kết nối, OpenAPI, phương pháp đề xuất |
| `POST` | `/api/ai/generate` | `{text, url, count, categories, authorized, review, auto_fix}` |
| `POST` | `/api/ai/autopilot` | `{url, username, password, paths, flow}` |
| `POST` | `/api/ai/run` | `{test_case_ids, url, classify, authorized, username, password}` |
| `POST` | `/api/ai/classify` | `{url, items}` phân loại kết quả không đạt |
| `POST` | `/api/ai/test-data/{id}?save=true` | Sinh dữ liệu theo phân vùng và giá trị biên |
| `POST` | `/api/ai/heal`, `/api/ai/heal/apply` | Đề xuất và áp dụng locator mới |
| `GET`, `PUT`, `DELETE` | `/api/test-cases`, `/api/test-cases/{id}` | Quản lý kịch bản |
| `POST` | `/api/test-cases/bulk-delete` | `{ids}` xoá mềm nhiều kịch bản |

**Quy ước của `test_case_ids`:** có danh sách thì chạy đúng các kịch bản đó, theo đúng thứ tự. Danh sách rỗng trả lỗi 400, không bao giờ được hiểu là chạy tất cả. Bỏ trường này mới là chạy toàn bộ (dành cho dòng lệnh). Phản hồi có `requested_cases`, `cases_run`, `not_found`, `total` (số lượt).

## Chất lượng

| Method | Endpoint | Mô tả |
| --- | --- | --- |
| `GET` | `/api/quality/metrics?url=` | Toàn bộ số liệu |
| `POST` | `/api/quality/benchmark` | `{url, source, ids}` đo phát hiện lỗi cài sẵn |
| `POST` | `/api/quality/review` | `{ids, url, use_ai}` duyệt kịch bản |
| `GET` | `/api/quality/reviews` | Kết quả duyệt |
| `POST` | `/api/quality/review/{id}/decision` | `{decision, reason}` người duyệt quyết định |
| `GET` | `/api/quality/agents` | Danh sách agent và nhật ký |
| `POST` | `/api/quality/demo-pack` | Nạp bộ mẫu viết tay |

## Kiến thức

| Method | Endpoint | Mô tả |
| --- | --- | --- |
| `GET`, `POST` | `/api/knowledge/skills` | Xem, tạo skill |
| `PUT`, `DELETE` | `/api/knowledge/skills/{id}` | Bật tắt, xoá skill |
| `GET`, `POST` | `/api/knowledge/lessons` | Xem, thêm bài học |
| `PUT`, `DELETE` | `/api/knowledge/lessons/{id}` | Đổi trạng thái, xoá |
| `POST` | `/api/knowledge/learn` | Rút bài học từ kết quả |
| `GET` | `/api/knowledge/dataset.jsonl` | Xuất dữ liệu huấn luyện |

## Bảo trì

| Method | Endpoint | Mô tả |
| --- | --- | --- |
| `GET` | `/api/maintenance/requirements` | Yêu cầu còn kịch bản |
| `POST` | `/api/maintenance/impact` | `{requirement_id, new_text}` phân tích ảnh hưởng |
| `POST` | `/api/maintenance/apply` | Áp dụng thay đổi |
| `GET` | `/api/maintenance/drift?url=` | API thay đổi |
| `POST` | `/api/maintenance/locators` | `{url}` phân tích DOM và locator |
| `GET` | `/api/maintenance/healings` | Đề xuất self-healing |
| `POST` | `/api/maintenance/healings/{id}` | `{decision}` áp dụng hoặc từ chối |

## Xuất file

| Method | Endpoint |
| --- | --- |
| `GET` | `/api/export/test-cases.xlsx?ids=`, `/api/export/test-cases.csv?ids=` |
| `POST` | `/api/export/report.xlsx` (gửi JSON kết quả của `/api/ai/run`) |

## Schema kịch bản

```json
{
  "id": "TC-A1B2-01",
  "title": "Đặt hàng hợp lệ trả về đúng tổng tiền",
  "type": "api",
  "priority": "high",
  "category": "functional",
  "technique": "happy",
  "covers": ["Đặt hàng hợp lệ trả về 201"],
  "data_sets": [{"name": "hop_le", "values": {"qty": 2}, "expected": "accept"}],
  "steps": [
    {"method": "POST", "path": "/api/shop/auth/register",
     "body": {"name": "Khách", "email": "{{$email}}", "password": "TestPilot#2026"},
     "expect": {"status": 201}},
    {"method": "POST", "path": "/api/shop/checkout", "body": {"...": "..."},
     "expect": {"status": 201, "json_contains": {"total": 39980000}},
     "save": {"order_id": "order_id"}}
  ]
}
```

| Trường của `expect` (API) | Ý nghĩa |
| --- | --- |
| `status`, `status_in`, `status_lt` | Mã trạng thái: đúng bằng, thuộc danh sách, nhỏ hơn |
| `json_contains` | Response chứa tập con này |
| `max_ms` | Thời gian phản hồi tối đa |
| `headers` | Các header phải có |
| `not_contains` | Các chuỗi không được xuất hiện |
| `cookie_flags` | Thuộc tính cookie phải có |
| `not_reflected_html` | Chuỗi này không được xuất hiện nguyên dạng trong HTML |

Bước UI: `{"action": "goto|click|fill|select|press|wait_for|assert_text|assert_visible", "url", "target": {"testid", "role", "name", "css"}, "value", "expect"}`.

Bước đo hiệu năng: `"perf": {"requests": 20, "concurrency": 5, "p95_ms": 800, "max_error_rate": 0}`.

Biến chạy: `{{$email}}`, `{{$uuid}}`, `{{$ts}}`, `{{$name}}` khác nhau mỗi lượt. Token dữ liệu: `<len:N>`, `<faker:email>`.

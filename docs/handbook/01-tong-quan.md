# Tổng quan và kiến trúc

TestPilot là nền tảng kiểm thử tự động ứng dụng AI. Đầu vào là yêu cầu nghiệp vụ hoặc địa chỉ website. Đầu ra là kịch bản kiểm thử dạng JSON có thể đọc và sửa, kết quả thực thi, nguyên nhân lỗi và báo cáo.

## Đầu ra của hệ thống

| Đầu ra | Dạng | Dùng để |
| --- | --- | --- |
| Kịch bản API | Bước HTTP: method, path, body, kết quả mong đợi | Kiểm thử nghiệp vụ, bảo mật, hiệu năng |
| Kịch bản UI | Bước trình duyệt: goto, click, fill, assert | Kiểm thử luồng người dùng |
| Báo cáo | Excel, CSV, JSON | Giao cho dev, kèm các bước tái hiện và lệnh curl |

AI chỉ sinh **dữ liệu JSON theo schema**, không sinh code. Runner đọc JSON để chạy. Nhờ vậy kết quả của AI luôn kiểm tra được, không có code lạ được thực thi trên máy.

## Kiến trúc

```text
Trình duyệt (frontend/*.html: Alpine.js, không cần build)
        |  JSON qua HTTP
FastAPI (backend/)
  main.py            test case, gắn router
  security.py        token, giới hạn tần suất, header, chặn SSRF
  ai_routes.py       sinh, thực thi, Autopilot, phân loại
  quality_routes.py  số liệu, duyệt, skill, bài học, bảo trì
  vault.py           tài khoản thử nghiệm, chỉ nằm trong bộ nhớ
  db.py              SQLite
        |
Module AI (ai/)
  agents.py          điều phối pipeline, ghi vết
  test_generator.py  Writer       review.py     Reviewer
  security_tests.py  Security, Performance
  autopilot.py       Explorer     classifier.py Triage
  healing.py         Healer       skills.py     skill và bài học
  quick_runner.py    chạy API     ui_runner.py  chạy UI bằng Playwright
  llm_provider.py    Gemini, Groq, OpenAI, Ollama; tự chuyển khi lỗi
        |
Hệ thống được kiểm thử: Demo Shop (ShopDemo/) hoặc website bất kỳ
```

## Luồng xử lý chính

1. **Đọc ngữ cảnh.** Tìm OpenAPI, lấy dữ liệu thật như mã sản phẩm và giá.
2. **Sinh.** Writer viết kịch bản chức năng. Security và Performance thêm kịch bản theo nhóm được chọn.
3. **Duyệt.** Reviewer chấm điểm bằng 17 luật, AI đối chiếu với tiêu chí chấp nhận. Verifier chạy thử trên hệ thống thật, Fixer sửa lỗi do kịch bản và chỉ giữ bản chạy lại đạt.
4. **Thực thi.** API chạy bằng HTTP, UI chạy bằng Playwright. Mỗi bộ dữ liệu là một lượt chạy riêng với phiên đăng nhập riêng.
5. **Phân tích.** Triage phân loại kết quả không đạt: lỗi ứng dụng, lỗi kịch bản hay không ổn định. Healer sửa locator hỏng.
6. **Học.** Learner rút bài học từ lỗi kịch bản. Người duyệt kích hoạt thì bài học mới có hiệu lực ở lần sinh sau.

## Vì sao không tự huấn luyện mô hình

| | Tự huấn luyện | Skill và bài học (đang dùng) |
| --- | --- | --- |
| Dữ liệu cần có | Hàng nghìn ví dụ đã gán nhãn | Không cần trước; tích luỹ dần |
| Hạ tầng | GPU, nhiều ngày đến nhiều tuần | Không cần thêm |
| Cập nhật kiến thức | Huấn luyện lại | Sửa một file văn bản, có hiệu lực ngay |
| Giải thích được | Khó | Đọc được từng quy tắc, biết lượt nào dùng quy tắc nào |
| Đổi nhà cung cấp LLM | Mất kết quả huấn luyện | Giữ nguyên |

Con đường huấn luyện vẫn để ngỏ: mỗi kịch bản được duyệt là một mẫu dữ liệu. Trang Agents có nút xuất **bộ dữ liệu JSONL** đúng định dạng fine-tune. Khi đủ dữ liệu, có thể fine-tune mô hình rồi dùng qua Ollama hoặc API tương thích OpenAI mà không phải đổi kiến trúc.

## Giới hạn hiện tại

- Autopilot theo liên kết `<a>`, chưa tự khám phá các màn hình chỉ mở ra sau khi bấm nút. Bù lại bằng cách cung cấp đường đi (xem tài liệu Autopilot).
- Kiểm thử hiệu năng là phép đo nhẹ để phát hiện suy giảm, không thay thế công cụ kiểm thử tải như k6 hay Locust.
- Kiểm thử bảo mật phát hiện các điểm yếu phổ biến, không thay thế kiểm thử xâm nhập do chuyên gia thực hiện.
- Chất lượng sinh phụ thuộc mô hình và hạn mức của nhà cung cấp. Hạn mức miễn phí có thể làm chậm lượt sinh lớn.

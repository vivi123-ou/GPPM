# Hướng dẫn sử dụng

## Kiểm thử một website trong 5 bước

1. **Nhập địa chỉ.** Mở trang **Kiểm thử**, nhập URL website hoặc link `openapi.json`, bấm **Kiểm tra**. TestPilot báo kết nối, có OpenAPI hay không và đề xuất cách tạo kịch bản.
2. **Tạo kịch bản.**
   - Có yêu cầu nghiệp vụ: chọn tab *Từ yêu cầu nghiệp vụ*, mô tả chức năng và tiêu chí chấp nhận, chọn nhóm (Chức năng, Bảo mật, Hiệu năng), bấm **Tạo kịch bản**.
   - Chỉ có website: chọn tab *Tự động khám phá*, có thể nhập đường đi cần kiểm thử, bấm **Chỉ khám phá** hoặc **Tự động toàn bộ**.
3. **Xem xét.** Danh sách chỉ hiện lô vừa tạo. Mỗi kịch bản có điểm duyệt 0 đến 100. Bấm vào tiêu đề để xem vấn đề, các bước, rồi **Chấp nhận** hoặc **Từ chối** kèm lý do.
4. **Thực thi.** Tick các kịch bản cần chạy, bấm **Thực thi**. Chỉ những dòng đang tick và đang hiển thị mới được chạy.
5. **Đọc báo cáo.** Mỗi lượt không đạt có nguyên nhân, các bước tái hiện, lệnh curl (API) hoặc ảnh màn hình (UI). Xuất Excel hoặc JSON để gửi cho dev.

## Chọn kịch bản

| Thao tác | Kết quả |
| --- | --- |
| Không tick gì | Nút Thực thi bị khoá. TestPilot không tự chạy toàn bộ |
| Tick 4 kịch bản | Chạy đúng 4 kịch bản |
| Đổi lô ở ô chọn lô | Bỏ các tick cũ để không mang lựa chọn sang lô khác |
| Lọc theo nhóm hoặc tìm kiếm | Dòng bị ẩn không được chạy, kể cả khi đã tick trước đó |

**Kịch bản và lượt chạy là hai con số khác nhau.** Một kịch bản có 3 bộ dữ liệu sẽ chạy 3 lượt. Dòng tóm tắt và báo cáo ghi rõ cả hai, ví dụ "4 kịch bản · 5 lượt chạy".

## Website cần đăng nhập

Tích *Website yêu cầu đăng nhập* và nhập **tài khoản thử nghiệm**. Không dùng tài khoản thật. Mật khẩu chỉ nằm trong bộ nhớ của server trong phiên làm việc, không gửi cho AI, không ghi vào kịch bản hay báo cáo. Sau khi khởi động lại server cần nhập lại.

## Kiểm thử bảo mật và hiệu năng

Tick nhóm **Bảo mật** hoặc **Hiệu năng** khi tạo kịch bản. Với website bên ngoài phải xác nhận *Tôi có quyền kiểm thử hệ thống này*. Không dùng các kịch bản này trên hệ thống bạn không được phép kiểm thử.

## Demo Shop và lỗi cài sẵn

Mục *Mô phỏng lỗi* bật các lỗi có chủ đích:

| Cờ | Tác dụng |
| --- | --- |
| `wrong_total` | Tổng tiền cộng thừa 100.000đ |
| `allow_empty_email` | Bỏ kiểm tra email |
| `ignore_stock` | Cho đặt vượt tồn kho |
| `ui_v2` | Đổi giao diện và `data-testid`, làm gãy locator cũ để thử self-healing |

**Nạp bộ kịch bản mẫu** tạo một bộ viết sẵn, không cần AI, dùng khi mạng hoặc hạn mức AI gặp sự cố. Bộ mẫu không được tính vào số liệu của AI.

## Các trang khác

| Trang | Nội dung |
| --- | --- |
| Chất lượng | Tỉ lệ đo được, phép đo phát hiện lỗi, lịch sử chạy |
| Agents | Danh sách agent, skill, bài học, nhật ký pipeline, xuất dữ liệu huấn luyện |
| Bảo trì | Yêu cầu thay đổi, API thay đổi, phân tích DOM và locator, duyệt self-healing |

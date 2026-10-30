# Autopilot

Autopilot nhận một URL và tự tạo kịch bản mà không cần tài liệu yêu cầu.

## Cách hoạt động

1. **Tìm OpenAPI** ở các đường dẫn phổ biến (`/openapi.json`, `/v3/api-docs`, `/swagger/v1/swagger.json`, ...).
2. **Duyệt trang.** Playwright mở trang đầu rồi đi theo liên kết cùng tên miền theo chiều rộng (BFS), mặc định tối đa 6 trang.
3. **Đăng nhập nếu cần.** Gặp ô mật khẩu và có tài khoản thử nghiệm thì điền, gửi form, chờ chuyển trang rồi khám phá tiếp phần sau đăng nhập. Bỏ qua liên kết đăng xuất.
4. **Rút phần tử** từ DOM mỗi trang, lập bản đồ trang.
5. **AI đề xuất kịch bản UI.** Chỉ được dùng phần tử có trong danh sách, ưu tiên luồng nhiều bước đi qua nhiều trang.
6. **Sinh kịch bản API** nếu có OpenAPI.
7. **Duyệt.** Reviewer chấm điểm, Fixer sửa kịch bản bị chê.

Nút **Tự động toàn bộ** chạy tiếp: thực thi, phân loại lỗi, tải báo cáo Excel.

## Cung cấp đường đi

Autopilot không biết nghiệp vụ, và có những màn hình không có liên kết dẫn tới. Người dùng có thể chỉ đường ở hai ô:

- **Đường đi cần kiểm thử**: mô tả luồng, ví dụ `đăng nhập → thêm sản phẩm vào giỏ → đặt hàng → thấy mã đơn`. AI ưu tiên các luồng này.
- **Trang cần duyệt**: mỗi dòng một đường dẫn, ví dụ `/shop/register`. Explorer duyệt các trang này dù không có liên kết dẫn tới.

## An toàn

- Mật khẩu không gửi cho AI. AI chỉ thấy `__USERNAME__` và `__PASSWORD__`, giá trị thật được thay vào lúc chạy.
- Nội dung website được coi là dữ liệu không đáng tin. Prompt yêu cầu AI không làm theo chỉ dẫn nằm trong trang, tóm tắt được thoát HTML khi hiển thị, kịch bản không thể đi ra ngoài website đang kiểm thử.
- Chỉ thao tác trên trang cùng tên miền.

## Giới hạn

- Chỉ theo liên kết `<a>`. Màn hình mở ra sau khi bấm nút (hộp thoại, giỏ hàng) chưa được tự khám phá; khi đó dùng ô đường đi.
- Trang có CAPTCHA hoặc đăng nhập SSO không tự vượt qua được.
- Kết quả phụ thuộc chất lượng DOM. Website thiếu `data-testid` và thiếu nhãn sẽ có kịch bản kém bền hơn; trang **DOM và locator** chỉ ra các điểm cần bổ sung.

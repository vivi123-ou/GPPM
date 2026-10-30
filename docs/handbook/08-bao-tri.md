# Bảo trì kịch bản

Chi phí lớn nhất của kiểm thử tự động không nằm ở lúc viết mà ở lúc bảo trì. Phần mềm đổi, kịch bản phải đổi theo. TestPilot theo dõi ba loại thay đổi ở trang **Bảo trì**.

## Yêu cầu thay đổi

Làm sao biết kịch bản nào cần đổi khi yêu cầu đổi? Mỗi kịch bản được **truy vết** về yêu cầu sinh ra nó (`requirement_id`) và về tiêu chí chấp nhận nó kiểm tra (`covers`).

1. Chọn yêu cầu, sửa nội dung, bấm **Phân tích ảnh hưởng**.
2. TestPilot hiện phần khác biệt, AI phân loại: **cần sửa**, **lỗi thời**, **giữ nguyên**, và các hành vi mới chưa có kịch bản.
3. Bấm **Áp dụng**:
   - Tạo phiên bản yêu cầu mới, liên kết với phiên bản cũ (`parent_id`).
   - Kịch bản lỗi thời chuyển trạng thái `obsolete`, dữ liệu vẫn còn.
   - AI viết lại kịch bản cần sửa, tăng số phiên bản.
   - AI sinh thêm kịch bản cho hành vi mới.
   - Duyệt lại toàn bộ. Kịch bản AI chưa sửa được sẽ bị đánh dấu cần xử lý tay, không bị bỏ qua âm thầm.

## API thay đổi

Mỗi lần sinh kịch bản, TestPilot lưu ảnh chụp danh sách endpoint. **Kiểm tra API** so sánh với OpenAPI hiện tại, không cần AI:

- Endpoint mới chưa có kịch bản.
- Endpoint bị bỏ.
- Kịch bản đang gọi endpoint không còn tồn tại.

## Giao diện thay đổi

- **DOM và locator**: đánh giá độ bền của locator trên trang hiện tại, chỉ ra phần tử nên bổ sung `data-testid`.
- **Self-healing**: khi locator gãy trong lúc chạy, Healer đề xuất locator mới đã chạy thử. Người duyệt áp dụng hoặc từ chối, lịch sử được lưu.

## Dọn dẹp

Ở trang Kiểm thử, tick các kịch bản không còn dùng rồi bấm **Xoá đã chọn**. Đây là xoá mềm: dữ liệu vẫn còn trong DB, chỉ không còn hiển thị.

## Lịch sử phiên bản

| Dữ liệu | Lưu ở |
| --- | --- |
| Phiên bản kịch bản | Cột `version` của `test_cases`, tăng khi sửa |
| Phiên bản yêu cầu | `requirements.parent_id` |
| Kết quả từng lượt | `runs`, `results` |
| Đề xuất self-healing | `healing_patches` |
| Vết pipeline agent | `agent_runs` |

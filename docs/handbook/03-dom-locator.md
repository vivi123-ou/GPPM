# DOM, locator và self-healing

## Khái niệm

**DOM** (Document Object Model) là cây đối tượng mà trình duyệt dựng từ HTML sau khi chạy JavaScript. Trang hiện đại tạo nhiều phần tử bằng JavaScript, nên HTML tải về có thể không có các nút cần bấm. TestPilot dùng Playwright mở trang thật và đọc DOM sau khi trang đã tải xong.

**Element** (phần tử) là một nút trong cây DOM, ví dụ một nút bấm hay một ô nhập.

**Locator** là cách chỉ ra phần tử cần thao tác. Ví dụ `[data-testid="checkout-button"]` hay vai trò `button` có tên `Đăng nhập`.

**Cây accessibility** là phiên bản DOM dành cho công nghệ hỗ trợ: mỗi phần tử có vai trò và tên, giống cách người dùng nhìn nhận. Locator theo vai trò dựa trên cây này.

## Từ DOM đến phần tử

Toàn bộ DOM rất lớn và nhiễu: gửi nguyên cho AI vừa tốn token vừa dễ sai. `ai/dom.py` lọc DOM thành danh sách phần tử gọn:

- Giữ phần tử tương tác (`a`, `button`, `input`, `select`, `textarea`), tiêu đề, phần tử có `data-testid` hoặc `role`, vùng thông báo.
- Bỏ `script`, `style`, `svg`.
- Tính vai trò ngầm định và tên hiển thị, lấy tên ô nhập từ `<label for>`.

Ví dụ một dòng gửi cho AI: `button "Đăng nhập" type=submit`. AI chỉ được chọn phần tử trong danh sách này, nên giảm rủi ro tự nghĩ ra phần tử không tồn tại.

## Thứ tự ưu tiên locator

Khi chạy, `ai/ui_runner.py` thử lần lượt:

| Ưu tiên | Loại | Điểm ổn định | Khi nào gãy |
| --- | --- | --- | --- |
| 1 | `data-testid`, `data-test`, `data-qa` | 100 | Gần như chỉ khi dev cố ý đổi |
| 2 | `id` | 85 (50 nếu id sinh tự động) | Id sinh tự động đổi mỗi lần build |
| 3 | Vai trò + tên | 75 | Đổi chữ trên giao diện |
| 4 | Label, placeholder | 60 | Đổi chữ trên giao diện |
| 5 | Văn bản | 45 | Dễ trùng, đổi theo nội dung |
| 6 | CSS | 30 | Đổi bố cục |

Locator chỉ dùng tốt khi **khớp đúng 1 phần tử**. Trang **Bảo trì → DOM và locator** mở trang thật, đề xuất locator cho từng phần tử, đếm số phần tử khớp và trừ điểm khi trùng. Reviewer cũng trừ điểm các CSS dễ gãy như `nth-child`.

## Self-healing

Vấn đề: dev đổi giao diện, kịch bản UI gãy dù chức năng vẫn đúng. Sửa tay rất tốn công.

Khi không tìm thấy phần tử sau thời gian chờ:

1. Lấy DOM hiện tại, rút thành danh sách phần tử.
2. Xếp hạng theo độ giống với locator cũ, giữ 25 ứng viên tốt nhất.
3. AI chọn ứng viên có cùng chức năng và giải thích thay đổi. Độ tin cậy dưới 0,5 thì bị bỏ.
4. Chạy thử ngay bước đó bằng locator mới, không chạy được thì không đề xuất.
5. Lượt chạy vẫn được đánh dấu **không đạt**, kèm đề xuất. Người duyệt bấm **Áp dụng** mới ghi vào kịch bản, tăng phiên bản.

Vì sao không tự ghi: một lần sửa sai có thể che giấu lỗi thật. Nếu nút thanh toán bị xoá nhầm mà AI chuyển sang một nút khác, bài kiểm thử sẽ đạt trong khi chức năng đã hỏng.

Khi AI không phản hồi, hệ thống chọn ứng viên giống nhất nếu điểm từ 0,55 và vẫn phải chạy thử được.

## Thử nghiệm

Bật cờ `ui_v2` của Demo Shop: các `data-testid` đổi tên (`add-iphone-15` thành `buy-iphone-15`, `checkout-button` thành `btn-place-order`) và chữ trên nút đổi. Thực thi kịch bản UI, sau đó xem đề xuất ở báo cáo hoặc **Bảo trì → Self-healing**.

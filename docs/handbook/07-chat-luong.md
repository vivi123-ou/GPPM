# Đo chất lượng

Trang **Chất lượng** tính mọi tỉ lệ từ dữ liệu thật trong SQLite. Chưa có dữ liệu thì hiển thị "chưa có số liệu". Bộ mẫu viết tay không được tính vào số liệu của AI.

## Các chỉ số

| Chỉ số | Công thức | Trả lời câu hỏi |
| --- | --- | --- |
| Sinh đúng định dạng | Kịch bản hợp lệ ở lần AI trả lời đầu ÷ tổng kịch bản AI trả về | AI có viết đúng schema không? |
| Qua được agent duyệt | Kịch bản từ 80 điểm, không có lỗi nặng ÷ kịch bản đã duyệt | Kịch bản có đạt tiêu chuẩn không? |
| Kịch bản dùng được | 1 − lỗi kịch bản ÷ lượt đã có kết luận | Khi chạy, kịch bản có đáng tin không? |
| Phủ endpoint | Endpoint có kịch bản ÷ endpoint trong OpenAPI | API đã được kiểm tra hết chưa? |
| Phủ tiêu chí chấp nhận | Tiêu chí có kịch bản ÷ tiêu chí AI tách từ yêu cầu | Yêu cầu đã được kiểm tra hết chưa? |
| Phát hiện lỗi cài sẵn | Lỗi bị bắt được ÷ tổng lỗi cài sẵn | Kịch bản có bắt được lỗi thật không? |

Không có một con số duy nhất cho "tỉ lệ sinh test case". Cần tách riêng: viết đúng định dạng, viết đúng ý, chạy được, và bắt được lỗi.

## Phép đo phát hiện lỗi

Đây là chỉ số quan trọng nhất vì trả lời câu hỏi kịch bản có giá trị hay không. Cách làm tương tự mutation testing:

1. Chạy các kịch bản API trên shop không có lỗi, ghi lại kịch bản đang đạt.
2. Bật một lỗi cài sẵn, reset dữ liệu, chạy lại.
3. Kịch bản đang đạt chuyển sang không đạt nghĩa là lỗi đó bị bắt được.
4. Lặp lại với từng lỗi, khôi phục trạng thái ban đầu.

Kịch bản đã không đạt từ đầu không được tính, tránh phồng số. Phép đo không gọi AI nên kết quả lặp lại được.

## Đánh giá A/B

`scripts/eval_skills.py` so sánh ba cấu hình trên cùng một yêu cầu, kết quả lưu ở `docs/eval/ket-qua.json`:

- **A**: không skill, không Reviewer, không Fixer.
- **B**: có skill, Reviewer, Fixer.
- **C**: như B, thêm bài học rút từ lỗi của B.

Số vòng nhỏ và mô hình AI có tính ngẫu nhiên, nên kết quả là tín hiệu định hướng, chưa phải kết luận thống kê. Muốn kết luận chắc chắn cần nhiều yêu cầu và nhiều vòng hơn.

## Đọc số liệu cho đúng

- Tỉ lệ đạt cao chưa chắc là tốt: kịch bản yếu thì luôn đạt. Xem cùng với phép đo phát hiện lỗi.
- Kết quả **lỗi ứng dụng** là kịch bản đã làm đúng việc, không phải điểm trừ của AI.
- Điểm duyệt do luật chấm chỉ phát hiện lỗi về hình thức. Kịch bản 100 điểm vẫn có thể kiểm tra sai ý; vì vậy có thêm AI đối chiếu và người duyệt.

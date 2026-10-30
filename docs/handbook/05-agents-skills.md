# Agents và skills

## Agent

Agent là một đơn vị có **một việc rõ ràng**, đầu vào và đầu ra xác định. Điều phối nằm ở `ai/agents.py`. Một agent lỗi không làm hỏng cả lượt: phần còn lại vẫn chạy và lỗi được ghi vào nhật ký.

| Agent | Việc | Cần LLM |
| --- | --- | --- |
| Context | Đọc OpenAPI và dữ liệu thật của hệ thống | Không |
| Explorer | Autopilot: duyệt website, lập bản đồ trang, đề xuất luồng UI | Có |
| Writer | Viết kịch bản chức năng từ yêu cầu | Có |
| Expander | Khi cần số lượng lớn: sinh kịch bản từ OpenAPI và dữ liệu thật, không tốn hạn mức | Không |
| Security | Dò theo OWASP từ OpenAPI (không cần AI), thêm lỗi logic nghiệp vụ (AI) | Một phần |
| Performance | Đo p50, p95, tỉ lệ lỗi ở tải nhẹ | Không |
| Reviewer | Chấm điểm bằng 17 luật, đối chiếu tiêu chí chấp nhận bằng AI | Một phần |
| Lead | Lập kế hoạch, giao việc, giao viết thêm khi thiếu tiêu chí, kết luận | Có |
| Verifier | Chạy thử trên hệ thống thật, chạy lại để nhận biết không ổn định | Không |
| Fixer | Sửa theo nhận xét và lỗi chạy thử; không được giảm kiểm tra; bản sửa theo lỗi chạy thử chỉ được giữ khi chạy lại đạt | Có |
| Triage | Phân loại kết quả không đạt | Một phần |
| Healer | Đề xuất locator thay thế, chạy thử trước khi đề xuất | Một phần |
| Learner | Rút bài học từ lỗi kịch bản và lý do từ chối | Có |

Mỗi lượt được ghi vào bảng `agent_runs`: agent nào chạy, bao lâu, model nào, dùng skill nào. Xem ở trang **Agents**.

## Skill

Skill là một file văn bản chứa kiến thức QA, được đưa vào ngữ cảnh của LLM. Skill có sẵn nằm ở `ai/skills/*.md`:

```markdown
---
id: auth-session
name: Xác thực và phiên đăng nhập
agents: [writer, reviewer, explorer]
triggers: [đăng nhập, đăng ký, login, checkout]
---
- Each case starts logged out. If an endpoint needs a user, register {{$email}} ...
```

- `agents`: agent nào dùng skill này.
- `triggers`: chỉ nạp khi yêu cầu chứa một trong các từ này, giúp tiết kiệm token. Để trống là luôn nạp.
- Thân skill nên viết bằng tiếng Anh vì LLM bám chỉ dẫn tốt hơn, còn kết quả vẫn bằng tiếng Việt.

Thêm skill cho dự án mới ở trang **Agents → Thêm skill**, không cần sửa code. Có thể bật tắt từng skill để so sánh kết quả.

## Bài học: cách hệ thống tốt dần lên

```text
Sinh kịch bản → Duyệt → Thực thi → Learner rút bài học → Người duyệt kích hoạt
      ^                                                          |
      +----------------------------------------------------------+
```

Nguồn bài học:

- Kết quả không đạt được Triage kết luận là **lỗi kịch bản**. Ví dụ AI đoán API đăng ký trả 200 trong khi thực tế là 201.
- **Lý do** người duyệt ghi khi từ chối kịch bản.
- Bài học người dùng tự thêm.

**Bắt buộc có người duyệt** vì nội dung lỗi có thể đến từ website bên ngoài. Tự động đưa vào prompt sẽ mở đường cho việc đầu độc kiến thức. Bài học chờ duyệt không được dùng cho tới khi kích hoạt.

Bài học gắn với hệ thống cụ thể (host), nên kiến thức về website này không ảnh hưởng website khác.

## Reviewer: các luật tự động

Mỗi lỗi trừ điểm theo mức: nặng 30, vừa 12, nhẹ 4. Đạt khi từ 80 điểm và không có lỗi nặng; dưới 50 là loại.

| Mã | Mức | Nội dung |
| --- | --- | --- |
| R01 | Nặng | Dữ liệu chứa biểu thức code |
| R02 | Vừa | Giá trị bí mật viết thẳng |
| R03 | Nhẹ | Tiêu đề quá ngắn |
| R04 | Vừa | Trùng các bước với kịch bản khác |
| R10 | Nặng | Bước API không kiểm tra kết quả nào |
| R11 | Nặng | Đường dẫn không có trong OpenAPI |
| R12 | Nặng | Method không được hỗ trợ |
| R13 | Nặng | Mong đợi thành công nhưng thiếu trường bắt buộc |
| R14 | Vừa | Đăng ký bằng email cố định |
| R15 | Nặng | Gọi API cần đăng nhập mà chưa tạo phiên |
| R16 | Nhẹ | Chỉ kiểm tra mã trạng thái |
| R20 | Vừa | Kịch bản UI không bắt đầu bằng goto |
| R21 | Nặng | Kịch bản UI không có bước kiểm chứng |
| R22 | Vừa | Bước cuối không kiểm chứng kết quả |
| R23 | Nhẹ | Dưới 3 bước, chưa phải luồng người dùng |
| R24 | Vừa | Locator CSS dễ gãy |
| R25 | Nặng | `assert_text` không có nội dung mong đợi |

Ngoài luật, AI tìm lỗi về ý nghĩa: kỳ vọng mâu thuẫn với yêu cầu, tiêu chí chấp nhận chưa có kịch bản. Điểm chỉ là tín hiệu hỗ trợ, **người duyệt có quyết định cuối**.

## Xuất dữ liệu huấn luyện

`GET /api/knowledge/dataset.jsonl` xuất các kịch bản đã duyệt, gom theo yêu cầu, theo định dạng `messages`. Mật khẩu được che. Đây là dữ liệu sẵn sàng cho fine-tune khi đủ số lượng.

---
id: triage-rules
name: Quy tắc phân loại lỗi
description: Phân biệt lỗi ứng dụng, lỗi kịch bản và không ổn định dựa trên bằng chứng.
version: 1.0
agents: [triage]
---
- A security case that fails because the system allowed something forbidden is an app_bug: the case did its job.
- A performance case that exceeds its threshold is an app_bug only when repeated; one slow sample on a loaded machine may be flaky.
- Cite the evidence: expected value, actual value, and the rule that defines the expected value.

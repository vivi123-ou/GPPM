---
id: performance-smoke
name: Đo hiệu năng nhanh
description: Đo p50/p95 và tỉ lệ lỗi ở tải nhẹ để phát hiện suy giảm; không thay thế kiểm thử tải.
version: 1.0
agents: [writer, reviewer]
triggers: [hiệu năng, tốc độ, thời gian phản hồi, performance, latency, ms, giây]
---
- Use a "perf" step: {"requests": 20, "concurrency": 5, "p95_ms": 800, "max_error_rate": 0}.
- Only measure read endpoints in bulk. For writes assert one call with expect.max_ms.
- Take thresholds from the requirement when it states them; otherwise use the defaults and say they are defaults.
- This is a smoke check that catches regressions. Real load tests belong to dedicated tools such as k6 or Locust.

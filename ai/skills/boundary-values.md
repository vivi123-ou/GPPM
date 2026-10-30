---
id: boundary-values
name: Phân vùng tương đương và giá trị biên
description: Áp dụng EP/BVA có hệ thống cho mọi giới hạn số và độ dài.
version: 1.0
agents: [writer, reviewer]
triggers: [từ, đến, tối đa, tối thiểu, số lượng, độ dài, ký tự, giới hạn, min, max, limit, length, quantity, range]
---
- For each numeric limit test: just below minimum, minimum, maximum, just above maximum.
- For each length limit use the token <len:N> at the limit and at limit + 1; never write code to build strings.
- Group values with the same expected outcome in one case through data_sets; split accepted and rejected values into separate cases.
- Empty string, whitespace only, zero and negative numbers are separate partitions from "missing field".
- Compute expected totals from real prices in the provided data. If unsure of a number, do not assert it.

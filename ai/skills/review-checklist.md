---
id: review-checklist
name: Tiêu chí duyệt kịch bản
description: Những gì agent duyệt kiểm tra ngoài các luật tự động.
version: 1.0
agents: [reviewer]
---
- Would this case fail if the feature broke? If not, it detects nothing.
- Does the expected result follow from the requirement, or is it an assumption?
- Is the expected number correct when recomputed from the real data?
- Does the title describe the behaviour under test, in a way a developer can act on?
- List each acceptance criterion and which cases cover it; an uncovered criterion is the most valuable finding.

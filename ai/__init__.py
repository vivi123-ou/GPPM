# SPDX-License-Identifier: Apache-2.0
"""TestPilot AI module ("bộ não").

Các hàm công khai mà backend gọi qua backend/ai_client.py:
- test_generator.generate_test_cases(requirement_text, openapi_spec=None)
- data_generator.generate_test_data(test_case)
- ui_steps.generate_ui_steps(goal, accessibility_tree)
- classifier.classify_failure(test_case, result)
- healing.suggest_locator(step, dom_snapshot)
- autopilot.autopilot(url)
- impact.find_affected_tests(old_text, new_text, test_cases)
"""

__version__ = "0.1.0"

import json, os
from pathlib import Path

from dotenv import load_dotenv

from backend.models import TestCase, DataSet

load_dotenv()
USE_MOCK = os.getenv("USE_MOCK", "1") == "1"
MOCK_DIR = Path(__file__).parent / "mocks"
# Nếu đặt, AI sẽ đọc OpenAPI của Demo Shop để dùng đúng path API
DEMO_SHOP_URL = os.getenv("DEMO_SHOP_URL", "")

def _mock(name: str):
    return json.loads((MOCK_DIR / name).read_text(encoding="utf-8"))

def generate_test_cases(requirement_text: str) -> list[TestCase]:
    if USE_MOCK:
        raw = _mock("test_cases.json")
        return [TestCase.model_validate(x) for x in raw]   # validate để bắt lệch schema sớm
    from ai.autopilot import find_openapi
    from ai.test_generator import generate_test_cases as real
    spec = find_openapi(DEMO_SHOP_URL) if DEMO_SHOP_URL else None
    return real(requirement_text, openapi_spec=spec)

def generate_test_data(test_case: TestCase) -> list[DataSet]:
    if USE_MOCK:
        return [DataSet.model_validate(x) for x in _mock("test_data.json")]
    from ai.data_generator import generate_test_data as real
    return real(test_case)

def classify_failure(test_case: TestCase, result: dict) -> dict:
    if USE_MOCK:
        return _mock("classify.json")
    from ai.classifier import classify_failure as real
    return real(test_case, result)

def suggest_locator(step: dict, dom_snapshot: str) -> dict:
    if USE_MOCK:
        return _mock("suggest_locator.json")
    from ai.healing import suggest_locator as real
    return real(step, dom_snapshot)

def generate_ui_steps(goal: str, accessibility_tree: str, url: str = "/") -> list:
    if USE_MOCK:
        return [s for s in _mock("test_cases.json")[2]["steps"]]
    from ai.ui_steps import generate_ui_steps as real
    return real(goal, accessibility_tree, url)

def autopilot(url: str) -> dict:
    if USE_MOCK:
        return {"app_summary": "(mock) Demo Shop", "openapi_found": True, "pages": [],
                "test_cases": [TestCase.model_validate(x) for x in _mock("test_cases.json")]}
    from ai.autopilot import autopilot as real
    return real(url)

def find_affected_tests(old_text: str, new_text: str, test_cases: list) -> dict:
    if USE_MOCK:
        return {"affected": [], "uncovered": []}
    from ai.impact import find_affected_tests as real
    return real(old_text, new_text, test_cases)

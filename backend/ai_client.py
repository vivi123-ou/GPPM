import json, os
from pathlib import Path
from backend.models import TestCase, DataSet

USE_MOCK = os.getenv("USE_MOCK", "1") == "1"
MOCK_DIR = Path(__file__).parent / "mocks"

def _mock(name: str):
    return json.loads((MOCK_DIR / name).read_text(encoding="utf-8"))

def generate_test_cases(requirement_text: str) -> list[TestCase]:
    if USE_MOCK:
        raw = _mock("test_cases.json")
    else:
        # TODO: từ B  ->  from ai.test_generator import generate_test_cases as real
        raise NotImplementedError("Module AI của B chưa nối")
    return [TestCase.model_validate(x) for x in raw]   # validate để bắt lệch schema sớm

def generate_test_data(test_case: TestCase) -> list[DataSet]:
    if USE_MOCK:
        return [DataSet.model_validate(x) for x in _mock("test_data.json")]
    raise NotImplementedError

def classify_failure(test_case: TestCase, result: dict) -> dict:
    if USE_MOCK:
        return _mock("classify.json")
    raise NotImplementedError

def suggest_locator(step: dict, dom_snapshot: str) -> dict:
    if USE_MOCK:
        return _mock("suggest_locator.json")
    raise NotImplementedError
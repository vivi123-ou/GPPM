from typing import Literal, Optional, Any

from pydantic import BaseModel, Field

Action = Literal["goto", "click", "fill", "select", "press",
                 "wait_for", "assert_text", "assert_visible"]

class Target(BaseModel):
    testid: Optional[str] = None
    role: Optional[str] = None
    name: Optional[str] = None
    css: Optional[str] = None

class Step(BaseModel):
    # --- bước API ---
    method: Optional[str] = None
    path: Optional[str] = None
    headers: Optional[dict[str, str]] = None
    body: Optional[dict[str, Any]] = None
    # API: {"status":400,"json_contains":{...}}  |  UI assert: chuỗi mong đợi
    expect: Optional[Any] = None
    # --- bước UI ---
    action: Optional[Action] = None
    url: Optional[str] = None
    target: Optional[Target] = None
    value: Optional[str] = None

class DataSet(BaseModel):
    name: str
    values: dict[str, Any] = {}
    expected: str = "accept"          # accept | reject

class TestCase(BaseModel):
    id: str
    requirement_id: Optional[str] = None
    title: str
    type: Literal["api", "ui"]
    priority: Literal["low", "medium", "high"] = "medium"
    data_sets: list[DataSet] = Field(default_factory=list)
    steps: list[Step]
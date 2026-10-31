import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend import ai_client
from backend.ai_routes import router as ai_router
from backend.export import router as export_router
from backend.quality_routes import knowledge, maintenance, quality
from backend.security import security_middleware
from backend.db import get_conn, init_db
from backend.models import TestCase
from ShopDemo import router as demo_shop_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(title="TestPilot", lifespan=lifespan)
app.middleware("http")(security_middleware)

@app.exception_handler(Exception)
async def unexpected_error(request, exc):
    """Lỗi ngoài dự kiến: trả JSON để giao diện hiện thông báo; chi tiết chỉ ghi ở log của server."""
    logging.getLogger("testpilot").exception("Lỗi xử lý %s", request.url.path)
    return JSONResponse({"detail": "Có lỗi khi xử lý yêu cầu. Xem log của server để biết chi tiết."}, status_code=500)

app.include_router(demo_shop_router)
app.include_router(ai_router)
app.include_router(export_router)
app.include_router(quality)
app.include_router(knowledge)
app.include_router(maintenance)
app.mount(
    "/shop-assets",
    StaticFiles(directory=Path(__file__).resolve().parent.parent / "ShopDemo" / "static"),
    name="demo-shop-assets",
)

class RequirementIn(BaseModel):
    text: str

def _row_to_dict(r) -> dict:
    d = json.loads(r["json"])
    d["version"] = r["version"]
    return d

@app.post("/api/requirements")
def create_requirement(body: RequirementIn):
    if not body.text.strip():
        raise HTTPException(400, "Yêu cầu không được để trống")
    try:
        cases = ai_client.generate_test_cases(body.text)
    except Exception as e:
        raise HTTPException(502, f"AI lỗi: {e}")
    conn = get_conn()
    req_id = conn.execute("INSERT INTO requirements(text) VALUES (?)", (body.text,)).lastrowid
    for tc in cases:
        tc.requirement_id = f"REQ-{req_id}"
        conn.execute(
            "INSERT OR REPLACE INTO test_cases(id, requirement_id, json, version, status) "
            "VALUES (?,?,?,1,'active')",
            (tc.id, tc.requirement_id, tc.model_dump_json()))
    conn.commit(); conn.close()
    return {"requirement_id": req_id, "count": len(cases)}

@app.get("/api/test-cases")
def list_test_cases():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM test_cases WHERE status='active' ORDER BY id").fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]

@app.put("/api/test-cases/{tc_id}")
def update_test_case(tc_id: str, tc: TestCase):      # FastAPI tự validate theo schema
    conn = get_conn()
    cur = conn.execute(
        "UPDATE test_cases SET json=?, version=version+1 WHERE id=?",
        (tc.model_dump_json(), tc_id))
    conn.commit(); conn.close()
    if cur.rowcount == 0:
        raise HTTPException(404, "Không thấy test case")
    return {"ok": True}

class BulkDeleteIn(BaseModel):
    ids: list[str]

@app.post("/api/test-cases/bulk-delete")
def bulk_delete(body: BulkDeleteIn):
    """Dọn nhiều kịch bản cùng lúc (xoá mềm, dữ liệu vẫn còn trong DB)."""
    conn = get_conn()
    conn.executemany("UPDATE test_cases SET status='deleted' WHERE id=?", [(i,) for i in body.ids])
    conn.commit(); conn.close()
    return {"deleted": len(body.ids)}

@app.delete("/api/test-cases/{tc_id}")
def delete_test_case(tc_id: str):
    conn = get_conn()
    conn.execute("UPDATE test_cases SET status='deleted' WHERE id=?", (tc_id,))
    conn.commit(); conn.close()
    return {"ok": True}

# Phải đặt CUỐI CÙNG để không nuốt các route /api
FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")

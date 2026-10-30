"""Việc chạy nền để giao diện hiện tiến độ từng agent thay vì chờ im lặng một request dài.
Lưu trong bộ nhớ, chỉ giữ các việc gần nhất; mã việc khó đoán."""
import secrets
import threading
from urllib.parse import urlparse

from fastapi import HTTPException

_jobs: dict[str, dict] = {}
_lock = threading.Lock()
MAX_JOBS = 30
_targets: dict[str, threading.RLock] = {}


def target_lock(url: str) -> threading.RLock:
    """Các lượt thực thi trên cùng một hệ thống phải lần lượt: mỗi lượt có thể đặt lại dữ liệu của hệ thống đó."""
    host = urlparse(url).netloc.lower()
    with _lock:
        return _targets.setdefault(host, threading.RLock())


def start(fn) -> str:
    """fn(on_step) chạy trong luồng riêng và trả về kết quả."""
    job_id = secrets.token_urlsafe(12)
    job = {"id": job_id, "status": "running", "trace": [], "result": None, "error": None}
    with _lock:
        _jobs[job_id] = job
        for old in list(_jobs)[:-MAX_JOBS]:
            if _jobs[old]["status"] != "running":
                del _jobs[old]

    def on_step(steps: list[dict]) -> None:
        job["trace"] = steps

    def work():
        try:
            job["result"] = fn(on_step)
            job["status"] = "done"
        except HTTPException as e:
            job.update(status="error", error=str(e.detail))
        except Exception as e:
            job.update(status="error", error=f"Lỗi xử lý: {e}")

    threading.Thread(target=work, daemon=True).start()
    return job_id


def get(job_id: str) -> dict | None:
    return _jobs.get(job_id)

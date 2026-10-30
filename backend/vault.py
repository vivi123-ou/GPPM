"""Tài khoản thử nghiệm chỉ nằm trong bộ nhớ tiến trình, theo từng host.

Mật khẩu không bao giờ ghi xuống SQLite hay gửi cho AI: kịch bản chỉ lưu dấu __USERNAME__/__PASSWORD__,
giá trị thật được thay vào lúc thực thi. Khởi động lại server thì phải nhập lại tài khoản.
"""
import threading
from urllib.parse import urlparse

_store: dict[str, dict] = {}
_lock = threading.Lock()


def _host(url: str) -> str:
    return urlparse(url).netloc.lower()


def remember(url: str, username: str, password: str) -> None:
    with _lock:
        _store[_host(url)] = {"username": username, "password": password}


def get(url: str) -> dict | None:
    with _lock:
        return _store.get(_host(url))

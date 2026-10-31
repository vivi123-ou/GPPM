"""Lớp bảo vệ của chính TestPilot: kiểm tra địa chỉ đích (SSRF), token API, giới hạn tần suất, header bảo mật.

Biến môi trường:
  TESTPILOT_TOKEN         đặt giá trị thì mọi API của TestPilot yêu cầu header X-TestPilot-Token
  ALLOW_PRIVATE_TARGETS   local (mặc định): chỉ người dùng trên chính máy chủ mới được nhắm địa chỉ nội bộ
                          1: luôn cho phép, 0: luôn chặn
  AI_RATE_LIMIT           số lượt gọi AI/thực thi mỗi phút cho mỗi IP (mặc định 60)
"""
import hmac
import ipaddress
import os
import socket
import threading
import time
from collections import defaultdict, deque
from urllib.parse import urlparse

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

METADATA_HOSTS = {"metadata.google.internal", "metadata", "instance-data"}
_LOOPBACK_CLIENTS = {"127.0.0.1", "::1", "localhost", "testclient"}
_RATE_PATHS = ("/api/ai/generate", "/api/ai/autopilot", "/api/ai/jobs", "/api/ai/run", "/api/ai/classify", "/api/ai/heal",
               "/api/ai/test-data", "/api/ai/impact", "/api/quality/review", "/api/quality/benchmark",
               "/api/knowledge/learn", "/api/maintenance/impact", "/api/maintenance/apply",
               "/api/maintenance/locators")
MAX_BODY = 50 * 1024 * 1024
_NO_CSP = ("/docs", "/redoc")      # Swagger UI nạp tài nguyên từ CDN
CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
       "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; "
       "img-src 'self' data: blob:; connect-src 'self'; frame-src http: https:; frame-ancestors 'self'; "
       "object-src 'none'; base-uri 'self'; form-action 'self'")


def _ips(host: str) -> list:
    try:
        return [ipaddress.ip_address(host.strip("[]"))]
    except ValueError:
        pass
    try:
        return [ipaddress.ip_address(i[4][0].split("%")[0]) for i in socket.getaddrinfo(host, None)]
    except OSError:
        return []          # không phân giải được: để bước kết nối báo "không truy cập được"


def _is_metadata(ip) -> bool:
    return ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved


def is_local_target(url: str) -> bool:
    ips = _ips(urlparse(url).hostname or "")
    return bool(ips) and all(ip.is_loopback for ip in ips)


def check_target(url: str, client_host: str | None = None) -> None:
    """Chặn SSRF: chỉ http/https, không bao giờ cho metadata cloud/link-local;
    địa chỉ nội bộ chỉ cho phép khi người gọi ở trên chính máy chủ (xem ALLOW_PRIVATE_TARGETS)."""
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise HTTPException(400, "Địa chỉ không hợp lệ. Ví dụ: https://example.com")
    if u.username or u.password:
        raise HTTPException(400, "Không đưa tài khoản vào địa chỉ. Hãy nhập ở ô tài khoản thử nghiệm.")
    host = u.hostname.lower()
    ips = _ips(host)
    if host in METADATA_HOSTS or any(_is_metadata(ip) for ip in ips):
        raise HTTPException(403, "Địa chỉ này bị chặn: vùng metadata/link-local của hạ tầng.")
    if any(ip.is_private or ip.is_loopback for ip in ips):
        mode = os.getenv("ALLOW_PRIVATE_TARGETS", "local")
        if mode == "0" or (mode != "1" and client_host not in _LOOPBACK_CLIENTS):
            raise HTTPException(403, "Không được nhắm tới địa chỉ nội bộ từ máy khác (ALLOW_PRIVATE_TARGETS).")


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


class _Limiter:
    def __init__(self):
        self.hits: dict[str, deque] = defaultdict(deque)
        self.lock = threading.Lock()

    def allow(self, key: str, limit: int, window: float = 60.0) -> bool:
        now = time.monotonic()
        with self.lock:
            q = self.hits[key]
            while q and now - q[0] > window:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True


limiter = _Limiter()


async def security_middleware(request: Request, call_next):
    path = request.url.path
    is_api = path.startswith("/api/") and not path.startswith("/api/shop")

    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > MAX_BODY:
        return JSONResponse({"detail": "Dữ liệu gửi lên quá lớn."}, status_code=413)

    token = os.getenv("TESTPILOT_TOKEN", "")
    if token and is_api and path != "/api/ai/config":
        if not hmac.compare_digest(request.headers.get("x-testpilot-token", ""), token):
            return JSONResponse({"detail": "Cần token truy cập (X-TestPilot-Token)."}, status_code=401)

    if request.method == "POST" and path.startswith(_RATE_PATHS):
        limit = int(os.getenv("AI_RATE_LIMIT", "60"))
        if not limiter.allow(client_ip(request) or "?", limit):
            return JSONResponse({"detail": f"Vượt giới hạn {limit} lượt/phút. Vui lòng thử lại sau."},
                                status_code=429, headers={"Retry-After": "60"})

    response = await call_next(request)
    if not path.startswith(("/api/", "/shop-assets/images/")):
        # Giao diện đổi là phải thấy ngay: trình duyệt hỏi lại máy chủ thay vì dùng bản đã lưu
        response.headers.setdefault("Cache-Control", "no-cache")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
    if not path.startswith(_NO_CSP):
        response.headers.setdefault("Content-Security-Policy", CSP)
    return response

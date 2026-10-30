# SPDX-License-Identifier: Apache-2.0
"""Một httpx.Client dùng chung cho toàn bộ module AI.

Gọi httpx.get()/httpx.post() trực tiếp tạo client mới mỗi lần — trên Windows mất ~0,7s
chỉ để nạp chứng chỉ SSL. Dùng lại một client (giữ kết nối, thread-safe) còn ~10ms.
"""

from __future__ import annotations

import httpx


def _block_metadata(request: httpx.Request) -> None:
    """Website đích có thể chuyển hướng tới vùng metadata của hạ tầng: chặn ở mọi lượt gửi."""
    host = request.url.host.lower()
    if host.startswith("169.254.") or host in ("metadata.google.internal", "metadata"):
        raise httpx.UnsupportedProtocol(f"Địa chỉ bị chặn: {host}")


hooks = {"request": [_block_metadata]}
client = httpx.Client(timeout=30.0, follow_redirects=True, event_hooks=hooks,
                      limits=httpx.Limits(max_connections=50, max_keepalive_connections=20))

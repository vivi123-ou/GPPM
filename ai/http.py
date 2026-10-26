# SPDX-License-Identifier: Apache-2.0
"""Một httpx.Client dùng chung cho toàn bộ module AI.

Gọi httpx.get()/httpx.post() trực tiếp tạo client mới mỗi lần — trên Windows mất ~0,7s
chỉ để nạp chứng chỉ SSL. Dùng lại một client (giữ kết nối, thread-safe) còn ~10ms.
"""

from __future__ import annotations

import httpx

client = httpx.Client(timeout=30.0, follow_redirects=True,
                      limits=httpx.Limits(max_connections=50, max_keepalive_connections=20))

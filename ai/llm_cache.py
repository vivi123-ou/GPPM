# SPDX-License-Identifier: Apache-2.0
"""Lớp bọc LLM cho một lượt làm việc trên giao diện.

- Dùng lại câu trả lời cho đúng cùng một đầu vào: tiết kiệm hạn mức, lần sau gần như tức thì. Khoá là băm của
  toàn bộ prompt, nên đổi yêu cầu, API, dữ liệu, skill hay bài học đều gọi lại AI.
- Giới hạn thời gian chờ mỗi lần gọi, và khi AI đã hết hạn mức thì các bước sau không chờ lại:
  lượt chạy chuyển ngay sang phần không cần AI thay vì đứng vài phút mỗi bước.
"""

from __future__ import annotations

import hashlib
import json

from ai.llm_provider import WAIT_BUDGET, LLMError

CACHE_DAYS = 7
WAIT_SECONDS = 60.0


class CachedLLM:
    def __init__(self, llm, read_cache: bool = True, wait_seconds: float = WAIT_SECONDS):
        self.llm = llm
        self.read_cache = read_cache
        self.wait_seconds = wait_seconds
        self.hits = 0
        self.misses = 0
        self.down: str | None = None       # lý do AI không dùng được trong lượt này

    @property
    def name(self):
        return self.llm.name

    @property
    def model(self):
        return self.llm.model

    @property
    def last_used(self):
        return getattr(self.llm, "last_used", None)

    def _guarded(self, fn):
        if self.down:
            raise LLMError(f"AI không khả dụng trong lượt này: {self.down}")
        token = WAIT_BUDGET.set(self.wait_seconds)
        try:
            return fn()
        except LLMError as e:
            self.down = str(e)[:160]
            raise
        finally:
            WAIT_BUDGET.reset(token)

    def complete(self, system: str, user: str, json_mode: bool = False) -> str:
        return self._guarded(lambda: self.llm.complete(system, user, json_mode))

    def complete_json(self, system: str, user: str):
        from backend.db import get_conn
        key = hashlib.sha256(f"{system}\0{user}".encode("utf-8")).hexdigest()
        if self.read_cache:
            conn = get_conn()
            row = conn.execute("SELECT response FROM llm_cache WHERE key=? AND created_at > datetime('now', ?)",
                               (key, f"-{CACHE_DAYS} days")).fetchone()
            conn.close()
            if row:
                self.hits += 1
                return json.loads(row["response"])
        data = self._guarded(lambda: self.llm.complete_json(system, user))
        self.misses += 1
        conn = get_conn()
        conn.execute("INSERT OR REPLACE INTO llm_cache(key, response, created_at) VALUES (?,?,CURRENT_TIMESTAMP)",
                     (key, json.dumps(data, ensure_ascii=False)))
        conn.commit()
        conn.close()
        return data

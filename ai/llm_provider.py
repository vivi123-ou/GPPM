# SPDX-License-Identifier: Apache-2.0
"""Lớp LLMProvider: một interface, nhiều backend (Gemini, Groq, OpenAI, Ollama).

Chọn provider bằng biến môi trường:
    LLM_PROVIDER=gemini|groq|openai|ollama   (mặc định: gemini)
    LLM_MODEL=...                     (tuỳ chọn, ghi đè model mặc định)
    GEMINI_API_KEY / GROQ_API_KEY / OPENAI_API_KEY   (khoá API)
    OLLAMA_URL=http://localhost:11434

Chỉ dùng httpx (đã có trong requirements), không cần SDK riêng.
"""

from __future__ import annotations

import os
import time
from abc import ABC, abstractmethod

import httpx

from ai.json_utils import parse_json


class LLMError(RuntimeError):
    pass


class LLMProvider(ABC):
    name = "base"
    default_model = ""

    def __init__(self, model: str | None = None, temperature: float = 0.2,
                 timeout: float = 60.0, max_retries: int = 2):
        self.model = model or os.getenv("LLM_MODEL") or self.default_model
        self.temperature = temperature
        self.timeout = timeout
        self.max_retries = max_retries

    @abstractmethod
    def _complete(self, system: str, user: str, json_mode: bool) -> str:
        """Gọi API thật, trả về text thô."""

    def complete(self, system: str, user: str, json_mode: bool = False) -> str:
        last: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                return self._complete(system, user, json_mode)
            except httpx.HTTPStatusError as e:
                last = e
                # 429/5xx: thử lại có backoff; 4xx khác: lỗi cấu hình, dừng luôn
                if e.response.status_code not in (429, 500, 502, 503, 504):
                    raise LLMError(f"{self.name} {e.response.status_code}: {e.response.text[:300]}") from e
            except httpx.HTTPError as e:
                last = e
            time.sleep(1.5 * (attempt + 1))
        raise LLMError(f"{self.name} lỗi sau {self.max_retries + 1} lần thử: {last}")

    def complete_json(self, system: str, user: str) -> dict | list:
        """Gọi LLM và parse JSON. Nếu JSON hỏng, gửi lại kèm lỗi để AI tự sửa (1 lần)."""
        text = self.complete(system, user, json_mode=True)
        try:
            return parse_json(text)
        except ValueError as e:
            fix = (f"{user}\n\nCâu trả lời trước của bạn không phải JSON hợp lệ ({e}). "
                   "Chỉ trả về đúng một đối tượng JSON, không kèm giải thích.")
            return parse_json(self.complete(system, fix, json_mode=True))


class GeminiProvider(LLMProvider):
    name = "gemini"
    default_model = "gemini-3.5-flash"
    BASE = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(self, api_key: str | None = None, **kw):
        super().__init__(**kw)
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            raise LLMError("Thiếu GEMINI_API_KEY")

    def _complete(self, system, user, json_mode):
        cfg: dict = {"temperature": self.temperature}
        if json_mode:
            cfg["responseMimeType"] = "application/json"
        r = httpx.post(
            f"{self.BASE}/{self.model}:generateContent",
            headers={"x-goog-api-key": self.api_key},
            json={"systemInstruction": {"parts": [{"text": system}]},
                  "contents": [{"role": "user", "parts": [{"text": user}]}],
                  "generationConfig": cfg},
            timeout=self.timeout)
        r.raise_for_status()
        data = r.json()
        try:
            return "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
        except (KeyError, IndexError) as e:
            raise LLMError(f"Gemini trả về không có nội dung: {str(data)[:300]}") from e


class OpenAICompatibleProvider(LLMProvider):
    """Dùng chung cho Groq (và bất kỳ API kiểu OpenAI nào)."""
    base_url = ""
    key_env = ""

    def __init__(self, api_key: str | None = None, **kw):
        super().__init__(**kw)
        self.api_key = api_key or os.getenv(self.key_env)
        if not self.api_key:
            raise LLMError(f"Thiếu {self.key_env}")

    def _complete(self, system, user, json_mode):
        body: dict = {"model": self.model, "temperature": self.temperature,
                      "messages": [{"role": "system", "content": system},
                                   {"role": "user", "content": user}]}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        r = httpx.post(f"{self.base_url}/chat/completions",
                       headers={"Authorization": f"Bearer {self.api_key}"},
                       json=body, timeout=self.timeout)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


class OpenAIProvider(OpenAICompatibleProvider):
    """ChatGPT (trả phí theo token)."""
    name = "openai"
    default_model = "gpt-5-mini"
    base_url = "https://api.openai.com/v1"
    key_env = "OPENAI_API_KEY"

    def __init__(self, **kw):
        super().__init__(**kw)
        self.base_url = os.getenv("OPENAI_BASE_URL", self.base_url).rstrip("/")


class GroqProvider(OpenAICompatibleProvider):
    name = "groq"
    default_model = "llama-3.3-70b-versatile"
    base_url = "https://api.groq.com/openai/v1"
    key_env = "GROQ_API_KEY"


class OllamaProvider(LLMProvider):
    name = "ollama"
    default_model = "qwen2.5:7b"

    def __init__(self, base_url: str | None = None, **kw):
        kw.setdefault("timeout", 180.0)   # model local chạy chậm hơn
        super().__init__(**kw)
        self.base_url = (base_url or os.getenv("OLLAMA_URL", "http://localhost:11434")).rstrip("/")

    def _complete(self, system, user, json_mode):
        body: dict = {"model": self.model, "stream": False,
                      "options": {"temperature": self.temperature},
                      "messages": [{"role": "system", "content": system},
                                   {"role": "user", "content": user}]}
        if json_mode:
            body["format"] = "json"
        r = httpx.post(f"{self.base_url}/api/chat", json=body, timeout=self.timeout)
        r.raise_for_status()
        return r.json()["message"]["content"]


PROVIDERS: dict[str, type[LLMProvider]] = {
    "gemini": GeminiProvider,
    "groq": GroqProvider,
    "openai": OpenAIProvider,
    "ollama": OllamaProvider,
}

_default: LLMProvider | None = None


def get_provider(name: str | None = None, **kw) -> LLMProvider:
    """Trả về provider theo tên hoặc LLM_PROVIDER. Provider mặc định được cache."""
    global _default
    if name is None and not kw and _default is not None:
        return _default
    key = (name or os.getenv("LLM_PROVIDER", "gemini")).lower()
    if key not in PROVIDERS:
        raise LLMError(f"LLM_PROVIDER không hợp lệ: {key} (chọn: {', '.join(PROVIDERS)})")
    p = PROVIDERS[key](**kw)
    if name is None and not kw:
        _default = p
    return p


def set_provider(p: LLMProvider | None) -> None:
    """Thay provider mặc định (dùng trong test với FakeProvider)."""
    global _default
    _default = p

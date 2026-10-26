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
import re
import threading
import time
from abc import ABC, abstractmethod

import httpx

from ai.json_utils import parse_json
from ai.http import client as _http


class LLMError(RuntimeError):
    pass


class RateLimitError(LLMError):
    """Provider từ chối vì vượt giới hạn tốc độ / hết hạn mức (HTTP 429)."""

    def __init__(self, msg: str, retry_after: float | None = None):
        super().__init__(msg)
        self.retry_after = retry_after


MAX_RATE_WAIT = float(os.getenv("LLM_MAX_RATE_WAIT", "60"))    # giây; lâu hơn = hết hạn mức theo ngày
COOLDOWN_SECONDS = float(os.getenv("LLM_COOLDOWN", "600"))     # tạm bỏ qua provider hết hạn mức
FALLBACK_MAX_WAIT = float(os.getenv("LLM_MAX_WAIT", "240"))    # tổng thời gian chờ tối đa cho một lần gọi
MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "16000"))


def _retry_after(resp: httpx.Response) -> float | None:
    """Số giây cần chờ: header Retry-After (Groq, OpenAI) hoặc retryDelay trong body (Gemini)."""
    h = resp.headers.get("retry-after")
    if h:
        try:
            return float(h)
        except ValueError:
            pass
    m = re.search(r'"retryDelay"\s*:\s*"([\d.]+)s"', resp.text or "")
    if m:
        return float(m.group(1))
    if "quota" in (resp.text or "").lower() and "per day" in (resp.text or "").lower():
        return 86400.0
    return None


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
            wait = 1.5 * (attempt + 1)
            try:
                return self._complete(system, user, json_mode)
            except httpx.HTTPStatusError as e:
                last = e
                code = e.response.status_code
                if code == 429:
                    # Không tự chờ ở đây: FallbackProvider chuyển sang model/provider khác,
                    # hoặc chờ đúng thời gian server yêu cầu nếu mọi cái đều đang bị giới hạn.
                    ra = _retry_after(e.response)
                    what = "hết hạn mức" if ra and ra > MAX_RATE_WAIT else "vượt giới hạn tốc độ"
                    raise RateLimitError(f"{self.name}/{self.model} {what} (429"
                                         + (f", chờ {ra:.0f}s)" if ra else ")"), ra) from e
                # 5xx: thử lại có backoff; 4xx khác: lỗi cấu hình, dừng luôn
                elif code not in (500, 502, 503, 504):
                    raise LLMError(f"{self.name} {code}: {e.response.text[:300]}") from e
            except httpx.HTTPError as e:
                last = e
            if attempt < self.max_retries:
                time.sleep(wait)
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
        r = _http.post(
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

    def _extra(self) -> dict:
        """Tham số riêng của từng nhà cung cấp/model."""
        return {}

    def _complete(self, system, user, json_mode):
        body: dict = {"model": self.model, "temperature": self.temperature,
                      "messages": [{"role": "system", "content": system},
                                   {"role": "user", "content": user}], **self._extra()}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        r = _http.post(f"{self.base_url}/chat/completions",
                       headers={"Authorization": f"Bearer {self.api_key}"},
                       json=body, timeout=self.timeout)
        if json_mode and r.status_code == 400 and "json_validate_failed" in r.text:
            # Groq từ chối khi bản nháp JSON không hợp lệ: gọi lại ở chế độ thường, tự tách JSON sau
            body.pop("response_format")
            r = _http.post(f"{self.base_url}/chat/completions",
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
    default_model = "openai/gpt-oss-120b"
    base_url = "https://api.groq.com/openai/v1"
    key_env = "GROQ_API_KEY"

    def _extra(self) -> dict:
        extra = {"max_completion_tokens": MAX_TOKENS}
        if "gpt-oss" in self.model:
            extra["reasoning_effort"] = "low"   # bớt token "suy nghĩ", nhanh hơn và đỡ chạm giới hạn
        return extra


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
        r = _http.post(f"{self.base_url}/api/chat", json=body, timeout=self.timeout)
        r.raise_for_status()
        return r.json()["message"]["content"]


PROVIDERS: dict[str, type[LLMProvider]] = {
    "gemini": GeminiProvider,
    "groq": GroqProvider,
    "openai": OpenAIProvider,
    "ollama": OllamaProvider,
}

class FallbackProvider(LLMProvider):
    """Gọi lần lượt từng provider/model; cái đang lỗi hoặc bị giới hạn (429) thì chuyển cái sau.

    - 429 ngắn hạn (giới hạn token/phút): tạm nghỉ đúng số giây server yêu cầu.
    - 429 dài hạn (hết hạn mức ngày): nghỉ COOLDOWN_SECONDS.
    - Nếu mọi provider đều đang nghỉ: chờ tới khi cái sớm nhất sẵn sàng (tối đa FALLBACK_MAX_WAIT)."""

    def __init__(self, providers: list[LLMProvider]):
        super().__init__(model=providers[0].model, max_retries=0)
        self.providers = providers
        self.name = providers[0].name
        self.last_used: LLMProvider = providers[0]
        self._cooldown: dict[int, float] = {}     # index provider → thời điểm được dùng lại
        self._lock = threading.Lock()

    def _complete(self, system, user, json_mode):   # pragma: no cover - complete() được ghi đè
        raise NotImplementedError

    def complete(self, system: str, user: str, json_mode: bool = False) -> str:
        errors: dict[int, str] = {}
        broken: set[int] = set()            # lỗi khác 429 (sai khoá, model không tồn tại...) trong lượt này
        deadline = time.time() + FALLBACK_MAX_WAIT
        while True:
            now = time.time()
            for i, p in enumerate(self.providers):
                if i in broken or self._cooldown.get(i, 0) > now:
                    continue
                try:
                    text = p.complete(system, user, json_mode)
                    self.last_used = p
                    return text
                except RateLimitError as e:
                    rest = e.retry_after or 15.0
                    if rest > MAX_RATE_WAIT:
                        rest = COOLDOWN_SECONDS
                    with self._lock:
                        self._cooldown[i] = time.time() + rest
                    errors[i] = str(e)
                except LLMError as e:
                    broken.add(i)
                    errors[i] = str(e)
            waiting = [self._cooldown.get(i, 0) for i in range(len(self.providers)) if i not in broken]
            if not waiting or min(waiting) > deadline:
                raise LLMError(" | ".join(errors.values()) or "Không có provider nào khả dụng")
            time.sleep(max(0.5, min(waiting) - time.time()))


_default: LLMProvider | None = None


def get_provider(name: str | None = None, **kw) -> LLMProvider:
    """Trả về provider theo tên hoặc LLM_PROVIDER. Provider mặc định được cache.

    LLM_FALLBACK: danh sách dự phòng "provider" hoặc "provider:model", cách nhau dấu phẩy.
    Mặc định dùng 3 model của Groq (mỗi model có hạn mức token/phút riêng) rồi tới OpenAI.
    Provider nào chưa có khoá thì tự bỏ qua. Đặt LLM_FALLBACK= (rỗng) để tắt."""
    global _default
    if name is None and not kw and _default is not None:
        return _default
    key = (name or os.getenv("LLM_PROVIDER", "gemini")).lower()
    if key not in PROVIDERS:
        raise LLMError(f"LLM_PROVIDER không hợp lệ: {key} (chọn: {', '.join(PROVIDERS)})")
    p = PROVIDERS[key](**kw)
    if name is None and not kw:
        chain, seen = [p], {(p.name, p.model)}
        for entry in os.getenv("LLM_FALLBACK", DEFAULT_FALLBACK).split(","):
            b, _, model = entry.strip().partition(":")
            b = b.lower()
            if b not in PROVIDERS:
                continue
            model = model or PROVIDERS[b].default_model   # LLM_MODEL chỉ áp dụng cho provider chính
            if (b, model) in seen:
                continue
            try:
                chain.append(PROVIDERS[b](model=model))
                seen.add((b, model))
            except LLMError:
                pass
        _default = p = FallbackProvider(chain)
    return p


DEFAULT_FALLBACK = "groq,groq:qwen/qwen3.8-27b,groq:openai/gpt-oss-20b,openai"


def set_provider(p: LLMProvider | None) -> None:
    """Thay provider mặc định (dùng trong test với FakeProvider)."""
    global _default
    _default = p

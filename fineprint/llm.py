"""Model providers: read a PDF and return the structured terms.

- GeminiProvider: google-genai, the PDF sent as a document (the model sees tables and columns as
  printed), JSON constrained by response_json_schema, throttled with retries; a per-day quota error
  fails fast (QuotaExhausted).
- FakeProvider: scripted answers for tests.
"""
import asyncio
import json
import os
import time

from . import config
from .prompts import SCHEMA, SYSTEM

MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "5"))


class LLMError(Exception):
    """The call failed; the card falls back to "not found" / "check this yourself"."""


class QuotaExhausted(LLMError):
    """A per-day quota is used up; retrying today will not help."""


def _parse(text: str | None) -> dict:
    if not text:
        raise LLMError("empty response")
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise LLMError(f"invalid JSON: {text[:120]}") from e


class _RateLimiter:
    def __init__(self, rpm: float):
        self.interval, self.next_at, self.lock = 60.0 / max(rpm, 0.1), 0.0, asyncio.Lock()

    async def wait(self):
        async with self.lock:
            now = time.monotonic()
            delay = self.next_at - now
            self.next_at = max(now, self.next_at) + self.interval
        if delay > 0:
            await asyncio.sleep(delay)


class Provider:
    name = "none"
    model = "none"

    async def extract(self, pdf: bytes, user: str) -> tuple[dict, dict]:
        raise NotImplementedError


class GeminiProvider(Provider):
    name = "gemini"

    def __init__(self, model: str | None = None, client=None):
        from google import genai

        self.model = model or config.GEMINI_MODEL
        self._client = client or genai.Client(api_key=os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
        self._limiter = _RateLimiter(config.GEMINI_RPM)

    async def extract(self, pdf: bytes, user: str) -> tuple[dict, dict]:
        from google.genai import errors, types

        cfg = types.GenerateContentConfig(
            system_instruction=SYSTEM,
            response_mime_type="application/json",
            response_json_schema=SCHEMA,
            max_output_tokens=32000,
            temperature=config.TEMPERATURE,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        contents = [types.Part.from_bytes(data=pdf, mime_type="application/pdf"), user]
        delay = 5.0
        for attempt in range(MAX_RETRIES + 1):
            await self._limiter.wait()
            try:
                resp = await self._client.aio.models.generate_content(model=self.model, contents=contents, config=cfg)
                um = resp.usage_metadata
                usage = {"input_tokens": getattr(um, "prompt_token_count", 0) or 0,
                         "output_tokens": (getattr(um, "candidates_token_count", 0) or 0) + (getattr(um, "thoughts_token_count", 0) or 0)}
                return _parse(resp.text), usage
            except errors.APIError as e:
                details = (getattr(e, "details", None) or {}).get("error", {}).get("details", [])
                day = [v for d in details for v in d.get("violations", []) if "PerDay" in v.get("quotaId", "")]
                if day:
                    raise QuotaExhausted(f"Gemini daily quota exhausted for {self.model}: "
                                         f"{day[0].get('quotaId')}, limit {day[0].get('quotaValue', '?')}") from e
                if getattr(e, "code", None) not in (429, 500, 502, 503, 504) or attempt == MAX_RETRIES:
                    raise LLMError(f"Gemini {getattr(e, 'code', '?')}: {str(e)[:200]}") from e
            except LLMError:
                raise
            except Exception as e:  # dropped connection, timeout
                if attempt == MAX_RETRIES:
                    raise LLMError(f"Gemini transport error: {type(e).__name__}: {str(e)[:200]}") from e
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60.0)
        raise LLMError("unreachable")


class FakeProvider(Provider):
    """Returns scripted answers in order (cycling); an Exception in the list is raised."""

    name = "fake"
    model = "fake"

    def __init__(self, responses: list):
        self.responses, self.calls = responses, 0

    async def extract(self, pdf: bytes, user: str) -> tuple[dict, dict]:
        out = self.responses[self.calls % len(self.responses)]
        self.calls += 1
        if isinstance(out, Exception):
            raise out
        return json.loads(json.dumps(out)), {"input_tokens": 0, "output_tokens": 0}


def get_provider() -> Provider | None:
    if os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
        return GeminiProvider()
    return None

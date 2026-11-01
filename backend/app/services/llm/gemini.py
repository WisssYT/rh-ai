"""Gemini adapter using the official google-genai SDK (generate_content API).

* Trusted shared rubric content goes into system_instruction, which is the stable prefix of every
  screening request; the untrusted CV follows in the user content. Gemini 2.5+ models apply
  *implicit* prefix caching automatically when the prefix exceeds the model minimum; we do not create
  paid explicit cache objects.
* Cached-token counts are read only from usage_metadata.cached_content_token_count. When the field is
  absent we report None ("not reported"), never a guessed cache hit.
* No tools, function declarations, search grounding or URL context are configured.
"""

from __future__ import annotations

import re
import time

from ...config import get_settings
from .base import DraftRequest, ProviderError, ProviderResponse, QuotaExceeded, ScreeningRequest, Usage


def _retry_after(err) -> float | None:
    details = getattr(err, "details", None) or {}
    try:
        for d in (details.get("error", {}) or {}).get("details", []) or []:
            if str(d.get("@type", "")).endswith("RetryInfo"):
                m = re.match(r"([\d.]+)s", str(d.get("retryDelay", "")))
                if m:
                    return float(m.group(1))
    except AttributeError:
        return None
    return None


class GeminiProvider:
    name = "gemini"
    mode = "live"

    def __init__(self, api_key: str | None = None, model_id: str | None = None):
        from google import genai
        from google.genai import types

        s = get_settings()
        key = api_key if api_key is not None else s.gemini_api_key
        if not key:
            raise ProviderError("GEMINI_API_KEY is not configured")
        self._types = types
        self.model_id = model_id or s.gemini_model
        self._client = genai.Client(
            api_key=key, http_options=types.HttpOptions(timeout=int(s.ai_timeout_seconds * 1000))
        )

    def _call(self, system: str, user: str, schema: dict, max_tokens: int) -> ProviderResponse:
        from google.genai import errors

        s = get_settings()
        t = self._types
        cfg = t.GenerateContentConfig(
            system_instruction=system,
            temperature=s.ai_temperature,
            max_output_tokens=max_tokens,
            response_mime_type="application/json",
            response_json_schema=schema,
        )
        start = time.monotonic()
        try:
            resp = self._client.models.generate_content(model=self.model_id, contents=user, config=cfg)
        except errors.ClientError as e:
            if e.code == 429:
                raise QuotaExceeded(f"provider quota/rate limit: {e.status}", _retry_after(e)) from None
            raise ProviderError(f"provider rejected request: {e.code} {e.status}") from None
        except errors.ServerError as e:
            raise ProviderError(f"provider server error: {e.code}") from None
        except Exception as e:  # network/timeouts
            raise ProviderError(f"provider call failed: {type(e).__name__}") from None
        latency = int((time.monotonic() - start) * 1000)
        um = getattr(resp, "usage_metadata", None)
        usage = Usage()
        if um is not None:
            usage = Usage(
                prompt_tokens=um.prompt_token_count,
                cached_tokens=um.cached_content_token_count,  # None when the provider omits it
                output_tokens=um.candidates_token_count,
                thinking_tokens=um.thoughts_token_count,
                reported=um.prompt_token_count is not None,
            )
        text = resp.text or ""
        return ProviderResponse(text=text, model_id=getattr(resp, "model_version", None) or self.model_id,
                                latency_ms=latency, usage=usage)

    def evaluate_resume(self, req: ScreeningRequest) -> ProviderResponse:
        return self._call(req.system_prompt, req.user_prompt, req.response_schema, get_settings().ai_max_output_tokens)

    def draft_invitation(self, req: DraftRequest) -> ProviderResponse:
        return self._call(req.system_prompt, req.user_prompt, req.response_schema, 1024)

    def structured(self, task: str, req: DraftRequest) -> ProviderResponse:
        return self._call(req.system_prompt, req.user_prompt, req.response_schema, 1536)

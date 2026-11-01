"""One code path for every small AI-assist task (inbox triage, reply drafts, interview kits).

Same guarantees as screening: operator-controlled mode, durable daily budget, one AICallLog row per call,
strict schema validation (extra fields rejected), no tools, and never a silent replay substitute for live.
"""

from __future__ import annotations

import json

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from ..db import session_scope
from ..models import AICallLog
from . import llm
from .llm.base import DraftRequest


class AssistResult:
    def __init__(self, data: dict, mode: str, model_id: str):
        self.data, self.mode, self.model_id = data, mode, model_id


def run_structured(db: Session, task: str, system: str, user: str, schema: type[BaseModel],
                   context: dict) -> AssistResult:
    """Raises ProviderError / QuotaExceeded / ValueError; the caller decides what the human sees."""
    mode = llm.current_mode(db)
    llm.check_daily_budget(db, mode)
    provider = llm.provider_for_mode(mode)
    req = DraftRequest(system_prompt=system, user_prompt=user, response_schema=schema.model_json_schema(),
                       context=context)
    resp = provider.structured(task, req)
    try:
        out = schema.model_validate_json(resp.text)
        outcome = "ok"
    except ValidationError:
        out, outcome = None, "invalid_output"
    # Logged in its own committed transaction: a call counts against the budget even when the request fails.
    with session_scope() as log_db:
        log_db.add(AICallLog(purpose=task, mode=mode, model_id=resp.model_id, outcome=outcome,
                             latency_ms=resp.latency_ms, prompt_tokens=resp.usage.prompt_tokens,
                             cached_tokens=resp.usage.cached_tokens, output_tokens=resp.usage.output_tokens,
                             thinking_tokens=resp.usage.thinking_tokens, usage_reported=resp.usage.reported))
    if out is None:
        raise ValueError("the AI output did not match the required schema and was discarded")
    return AssistResult(out.model_dump(), mode, resp.model_id)


def untrusted_block(tag: str, text: str) -> str:
    """Wrap untrusted content so the prompt can refer to it; closing tags inside are neutralised."""
    clean = text.replace(f"</{tag}>", f"</ {tag}>").replace("\x00", "")
    return f"<{tag}>\n{clean}\n</{tag}>"


def trusted_json(ctx: dict) -> str:
    return "TRUSTED CONTEXT (JSON):\n" + json.dumps(ctx, ensure_ascii=False)

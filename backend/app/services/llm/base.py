from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class Usage:
    prompt_tokens: int | None = None
    cached_tokens: int | None = None  # ONLY from provider usage metadata; None = not reported
    output_tokens: int | None = None
    thinking_tokens: int | None = None
    reported: bool = False


@dataclass
class ProviderResponse:
    text: str
    model_id: str
    latency_ms: int
    usage: Usage = field(default_factory=Usage)


@dataclass
class ScreeningRequest:
    system_prompt: str  # trusted shared prefix
    user_prompt: str  # untrusted variable content
    response_schema: dict
    # structured copies for the deterministic replay adapter (never sent anywhere)
    application_ref: str = ""
    criteria: list[dict] = field(default_factory=list)
    redacted_pages: list[dict] = field(default_factory=list)


@dataclass
class DraftRequest:
    system_prompt: str
    user_prompt: str
    response_schema: dict
    context: dict = field(default_factory=dict)


class QuotaExceeded(Exception):
    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class ProviderError(Exception):
    pass


class LLMProvider(Protocol):
    name: str
    mode: str  # live | replay
    model_id: str

    def evaluate_resume(self, req: ScreeningRequest) -> ProviderResponse: ...

    def draft_invitation(self, req: DraftRequest) -> ProviderResponse: ...

    def structured(self, task: str, req: DraftRequest) -> ProviderResponse:
        """Generic JSON-schema task (inbox triage, reply drafts, interview kits). No tools."""
        ...

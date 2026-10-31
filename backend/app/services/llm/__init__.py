"""Provider selection, operator-controlled AI mode, and free-tier budgets."""

from __future__ import annotations

import threading
import time
from collections import deque
from datetime import datetime, time as dtime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...config import get_settings
from ...models import AICallLog, SystemSetting, utcnow
from .base import LLMProvider, ProviderError, QuotaExceeded  # noqa: F401
from .replay import ReplayProvider

_provider_override: LLMProvider | None = None  # tests inject mocks here


def set_provider_override(p: LLMProvider | None) -> None:
    global _provider_override
    _provider_override = p


def current_mode(db: Session) -> str:
    row = db.get(SystemSetting, "ai_mode")
    return row.value if row else get_settings().ai_mode


def set_mode(db: Session, mode: str, user_id: str) -> None:
    row = db.get(SystemSetting, "ai_mode")
    if row is None:
        db.add(SystemSetting(key="ai_mode", value=mode, updated_by=user_id))
    else:
        row.value, row.updated_by, row.updated_at = mode, user_id, utcnow()


def provider_for_mode(mode: str) -> LLMProvider:
    """Never substitutes replay for live: a live failure surfaces as an error."""
    if _provider_override is not None and _provider_override.mode == mode:
        return _provider_override
    if mode == "replay":
        return ReplayProvider()
    if mode == "live":
        if _provider_override is not None:
            raise ProviderError("test override does not provide live mode")
        from .gemini import GeminiProvider

        return GeminiProvider()
    raise ProviderError(f"unknown AI mode {mode}")


def model_id_for_mode(mode: str) -> tuple[str, str]:
    if _provider_override is not None and _provider_override.mode == mode:
        return _provider_override.name, _provider_override.model_id
    if mode == "replay":
        return "replay", ReplayProvider.model_id
    return "gemini", get_settings().gemini_model


def live_calls_today(db: Session) -> int:
    start = datetime.combine(datetime.now(timezone.utc).date(), dtime.min, tzinfo=timezone.utc)
    return db.scalar(
        select(func.count(AICallLog.id)).where(AICallLog.mode == "live", AICallLog.at >= start)
    ) or 0


class DailyBudgetExhausted(QuotaExceeded):
    pass


def check_daily_budget(db: Session, mode: str) -> None:
    if mode != "live":
        return
    if live_calls_today(db) >= get_settings().ai_daily_call_budget:
        raise DailyBudgetExhausted("AI_DAILY_CALL_BUDGET reached for today (UTC)")


class RpmLimiter:
    """Process-local requests-per-minute pacing for the worker."""

    def __init__(self) -> None:
        self._calls: deque[float] = deque()
        self._lock = threading.Lock()

    def wait(self, max_wait: float = 65.0) -> None:
        rpm = get_settings().ai_rpm
        deadline = time.monotonic() + max_wait
        while True:
            with self._lock:
                now = time.monotonic()
                while self._calls and self._calls[0] <= now - 60:
                    self._calls.popleft()
                if len(self._calls) < rpm:
                    self._calls.append(now)
                    return
                wait = 60 - (now - self._calls[0]) + 0.05
            if time.monotonic() + wait > deadline:
                raise QuotaExceeded("local AI_RPM pacing window exceeded", retry_after=wait)
            time.sleep(min(wait, 5))


rpm_limiter = RpmLimiter()

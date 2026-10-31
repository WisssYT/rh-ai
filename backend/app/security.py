from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import User, UserSession, utcnow

SESSION_COOKIE = "td_session"
CSRF_COOKIE = "td_csrf"
CSRF_HEADER = "x-csrf-token"

_hasher = PasswordHasher()  # argon2id with library defaults
_DUMMY_HASH = _hasher.hash("timing-equalizer-not-a-password")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def _token_hash(token: str) -> str:
    key = get_settings().session_secret.encode()
    return hmac.new(key, token.encode(), hashlib.sha256).hexdigest()


def create_session(db: Session, user: User) -> tuple[str, UserSession]:
    token = secrets.token_urlsafe(32)
    s = UserSession(
        token_hash=_token_hash(token),
        user_id=user.id,
        csrf_token=secrets.token_urlsafe(24),
        expires_at=utcnow() + timedelta(hours=get_settings().session_ttl_hours),
    )
    db.add(s)
    db.flush()
    return token, s


def lookup_session(db: Session, token: str | None) -> UserSession | None:
    if not token or len(token) > 200:
        return None
    s = db.scalar(select(UserSession).where(UserSession.token_hash == _token_hash(token)))
    if s is None or s.revoked_at is not None or s.expires_at <= utcnow():
        return None
    if not s.user.is_active:
        return None
    return s


def digest(obj) -> str:
    """Stable SHA-256 over a JSON-serializable object (sorted keys)."""
    raw = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(raw).hexdigest()


class RateLimiter:
    """Small in-process sliding-window limiter (single-process local demo).

    A multi-instance deployment would need a shared store; documented in SECURITY.md.
    """

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, window_s: float) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and q[0] <= now - window_s:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


rate_limiter = RateLimiter()

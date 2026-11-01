"""Application settings, loaded from environment variables (and an optional .env file).

Secrets (SESSION_SECRET, GEMINI_API_KEY, SUPERVISOR_PASSWORD) are server-side only.
Nothing here is ever exposed to the frontend bundle.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_SECRETS = {"", "change-me", "changeme", "dev-secret", "<generated local secret>"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore"
    )

    # Product
    product_name: str = "Talent Detective"
    company_name: str = "Nordlicht Robotics (fictional)"

    app_env: Literal["development", "test", "production"] = "development"
    demo_mode: bool = True
    database_url: str = "postgresql+psycopg://postgres@localhost:55432/talent"
    session_secret: str = "dev-secret"
    session_ttl_hours: int = 12
    public_app_url: str = "http://localhost:5173"
    company_timezone: str = "Africa/Tunis"
    cookie_secure: bool | None = None  # None -> derived from PUBLIC_APP_URL scheme

    # AI
    ai_mode: Literal["live", "replay"] = "replay"
    gemini_api_key: str = Field(default="", repr=False)
    gemini_model: str = "gemini-2.5-flash"
    ai_concurrency: int = 1
    ai_rpm: int = 5
    ai_daily_call_budget: int = 40
    ai_timeout_seconds: float = 60.0
    ai_max_output_tokens: int = 4096
    ai_max_retries: int = 2  # retries for invalid output
    ai_quota_retries: int = 2  # retries on 429 before pausing the run
    ai_temperature: float = 0.0
    analysis_runs_per_hour: int = 10

    # Email
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_from: str = "talent-detective@nordlicht.example.test"
    allow_external_email: bool = False
    mailpit_ui_url: str = "http://localhost:8025"

    # Uploads
    upload_dir: str = "./var/uploads"
    database_file_storage: bool = False  # durable CVs on hosts with ephemeral filesystems
    max_upload_bytes: int = 5 * 1024 * 1024
    max_pdf_pages: int = 10
    max_extracted_chars: int = 40_000
    pdf_parse_timeout_seconds: float = 15.0

    # Scheduling
    hold_minutes: int = 120
    invitation_valid_days: int = 7
    default_shortlist_size: int = 20

    # Seeding
    supervisor_email: str = "supervisor@nordlicht.example.test"
    supervisor_password: str = Field(default="", repr=False)

    @field_validator("company_timezone")
    @classmethod
    def _tz(cls, v: str) -> str:
        ZoneInfo(v)  # raises if unknown
        return v

    @field_validator("ai_concurrency", "ai_rpm", "ai_daily_call_budget", "max_pdf_pages")
    @classmethod
    def _positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("must be >= 1")
        return v

    @model_validator(mode="after")
    def _production_rules(self) -> "Settings":
        if self.app_env == "production":
            if self.session_secret in INSECURE_SECRETS or len(self.session_secret) < 32:
                raise ValueError("SESSION_SECRET must be a strong random value in production")
            if not self.public_app_url.startswith("https://"):
                raise ValueError("PUBLIC_APP_URL must use https in production")
        return self

    @property
    def secure_cookies(self) -> bool:
        if self.cookie_secure is not None:
            return self.cookie_secure
        return self.public_app_url.startswith("https://")

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.company_timezone)

    @property
    def upload_path(self) -> Path:
        p = Path(self.upload_dir).resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def live_ai_configured(self) -> bool:
        return bool(self.gemini_api_key.strip())

    def preflight(self) -> list[str]:
        """Human-readable configuration warnings (never contains secret values)."""
        notes: list[str] = []
        if not self.live_ai_configured:
            notes.append("GEMINI_API_KEY is not set: live AI analysis is disabled; replay mode remains available.")
        if self.session_secret in INSECURE_SECRETS:
            notes.append("SESSION_SECRET uses a development placeholder (acceptable only for local demo).")
        if self.allow_external_email:
            notes.append("ALLOW_EXTERNAL_EMAIL=true - external delivery is NOT recommended for this demo.")
        return notes


@lru_cache
def get_settings() -> Settings:
    return Settings()

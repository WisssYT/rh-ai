"""Test harness: real PostgreSQL (TEST_DATABASE_URL), mocked LLM provider, real app over TestClient."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable

import pytest

os.environ.setdefault("TEST_DATABASE_URL", "postgresql+psycopg://postgres@localhost:55432/talent_test")
os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
os.environ["APP_ENV"] = "test"
os.environ["AI_MODE"] = "replay"
os.environ["GEMINI_API_KEY"] = ""
os.environ["SESSION_SECRET"] = "test-secret-" + "x" * 40
os.environ["UPLOAD_DIR"] = tempfile.mkdtemp(prefix="td-test-uploads-")
os.environ["AI_RPM"] = "1000"
os.environ["AI_QUOTA_RETRIES"] = "1"
os.environ.setdefault("SMTP_HOST", "localhost")
os.environ.setdefault("SMTP_PORT", "1025")

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.cli import BACKEND_CRITERIA, _approve_rubric  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import Base, SessionLocal, get_engine, session_scope  # noqa: E402
from app.fixtures.cvs import render_pdf  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Company, Job, JobAssignment, User, utcnow  # noqa: E402
from app.security import hash_password, rate_limiter  # noqa: E402
from app.services import llm  # noqa: E402
from app.services.llm.base import ProviderResponse, Usage  # noqa: E402
from app.services.llm.replay import ReplayProvider  # noqa: E402

PW = "Sufficiently-Long-Pw1"
D = "example.test"


@pytest.fixture(scope="session", autouse=True)
def _schema():
    get_settings.cache_clear()
    eng = get_engine()
    with eng.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "alembic"))
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(autouse=True)
def _clean():
    eng = get_engine()
    with eng.begin() as c:  # DELETE is much faster than TRUNCATE for tiny tables (no file sync)
        for t in reversed(Base.metadata.sorted_tables):
            c.execute(t.delete())
    rate_limiter.reset()
    llm.set_provider_override(None)
    with session_scope() as db:
        db.add(Company(id=1, name="Test Co (fictional)", timezone="Africa/Tunis", contact_email=f"hr@{D}",
                       interview_instructions="45 minute video call."))
    yield
    llm.set_provider_override(None)


class Client:
    """Browser-like client: cookie jar + CSRF header handling."""

    def __init__(self):
        self.c = TestClient(app)
        self.csrf = self.c.get("/api/auth/csrf").json()["csrf_token"]

    def _h(self):
        return {"x-csrf-token": self.c.cookies.get("td_csrf") or self.csrf}

    def get(self, url, **kw):
        return self.c.get(url, **kw)

    def post(self, url, **kw):
        return self.c.post(url, headers={**self._h(), **kw.pop("headers", {})}, **kw)

    def put(self, url, **kw):
        return self.c.put(url, headers={**self._h(), **kw.pop("headers", {})}, **kw)

    def patch(self, url, **kw):
        return self.c.patch(url, headers={**self._h(), **kw.pop("headers", {})}, **kw)

    def delete(self, url, **kw):
        return self.c.delete(url, headers={**self._h(), **kw.pop("headers", {})}, **kw)

    def login(self, email, password=PW, portal="candidate"):
        r = self.post("/api/auth/login", json={"email": email, "password": password, "portal": portal})
        assert r.status_code == 200, r.text
        return self


def make_staff(email: str, role: str = "recruiter", name: str = "Staff Member") -> str:
    with session_scope() as db:
        u = User(email=email, full_name=name, role=role, password_hash=hash_password(PW))
        db.add(u)
        db.flush()
        return u.id


def make_job(assign_to: list[str] | None = None, slug: str = "backend", criteria=None) -> str:
    with session_scope() as db:
        sup = db.query(User).filter(User.role == "supervisor").first()
        if sup is None:
            sup = User(email=f"seed-sup-{slug}@{D}", full_name="Seed Sup", role="supervisor",
                       password_hash=hash_password(PW))
            db.add(sup)
            db.flush()
        j = Job(slug=slug, title="Backend Developer", description="Python APIs.", status="published",
                published_at=utcnow(), created_by=sup.id, shortlist_size=20, min_suggest_score=0)
        db.add(j)
        db.flush()
        _approve_rubric(db, j, criteria or BACKEND_CRITERIA, sup)
        for uid in assign_to or []:
            db.add(JobAssignment(job_id=j.id, user_id=uid))
        return j.id


def cv_pdf(name: str, email: str, extra: list[str] | None = None) -> bytes:
    lines = [name, email, "", "EXPERIENCE", "Backend Developer, Fictional Co, 2019 - 2025",
             "Developed Python services with FastAPI and REST APIs.", "Designed PostgreSQL schemas.",
             "Wrote pytest integration tests and deployed with Docker.", "", "SKILLS",
             "Skills: Python, FastAPI, PostgreSQL, pytest, Docker"] + (extra or [])
    return render_pdf([lines])


def register(name: str, email: str) -> Client:
    c = Client()
    r = c.post("/api/auth/register", json={"email": email, "full_name": name, "password": PW,
                                           "fictional_data_ack": True})
    assert r.status_code == 201, r.text
    return c


def apply(c: Client, job_id: str, pdf: bytes, filename: str = "cv.pdf"):
    return c.post(f"/api/jobs/{job_id}/applications", files={"file": (filename, pdf, "application/pdf")},
                  data={"storage_notice_ack": "true"})


def run_worker():
    from app.services import analysis

    return analysis.run_until_idle(session_scope)


class MockProvider:
    """Deterministic fake LLM for CI. `script` returns raw text given the request (or raises)."""

    name = "mock"
    model_id = "mock-model-1"

    def __init__(self, mode: str = "live", script: Callable | None = None, usage: Usage | None = None):
        self.mode = mode
        self.calls = 0
        self.draft_calls = 0
        self.script = script
        self.usage = usage if usage is not None else Usage(prompt_tokens=2500, cached_tokens=2048, output_tokens=300,
                                                           thinking_tokens=None, reported=True)
        self.requests = []

    def evaluate_resume(self, req):
        self.calls += 1
        self.requests.append(req)
        if self.script:
            out = self.script(req, self.calls)
            if isinstance(out, Exception):
                raise out
            return ProviderResponse(text=out, model_id=self.model_id, latency_ms=5, usage=self.usage)
        r = ReplayProvider().evaluate_resume(req)
        return ProviderResponse(text=r.text, model_id=self.model_id, latency_ms=5, usage=self.usage)

    def draft_invitation(self, req):
        self.draft_calls += 1
        self.requests.append(req)
        if self.script:
            out = self.script(req, self.draft_calls)
            if isinstance(out, Exception):
                raise out
            return ProviderResponse(text=out, model_id=self.model_id, latency_ms=5, usage=self.usage)
        return ProviderResponse(text=json.dumps({"subject": "Interview invitation",
                                                 "body": "Hello, we would like to invite you to an interview."}),
                                model_id=self.model_id, latency_ms=5, usage=self.usage)


@pytest.fixture
def db():
    s = SessionLocal()
    yield s
    s.close()


def set_mode(mode: str):
    with session_scope() as db:
        llm.set_mode(db, mode, "test")


def setup_shortlist(n: int = 2, slug: str = "backend"):
    """Job + assigned recruiter + n candidates who applied, analysed (replay) and human-approved shortlist."""
    rid = make_staff(f"rec-{slug}@{D}", name="Rec One")
    job_id = make_job([rid], slug=slug)
    rec = Client().login(f"rec-{slug}@{D}", portal="staff")
    cands, apps = [], []
    for i in range(n):
        email = f"cand{i}-{slug}@{D}"
        c = register(f"Candidate{i} Person", email)
        r = apply(c, job_id, cv_pdf(f"Candidate{i} Person", email))
        assert r.status_code == 201, r.text
        cands.append(c)
        apps.append(r.json()["id"])
    r = rec.post(f"/api/hr/jobs/{job_id}/analysis-runs",
                 json={"application_ids": apps, "rubric_revision": 1, "confirm_scope": True})
    assert r.status_code == 201, r.text
    run_worker()
    r = rec.post(f"/api/hr/jobs/{job_id}/shortlists", json={"members": [{"application_id": a} for a in apps]})
    assert r.status_code == 201, r.text
    sl = r.json()
    r = rec.post(f"/api/hr/jobs/{job_id}/shortlists/{sl['id']}/approve", json={"digest": sl["digest"]})
    assert r.status_code == 200, r.text
    return {"job_id": job_id, "rec": rec, "rec_id": rid, "cands": cands, "apps": apps, "shortlist": r.json()}


def send_invitations(ctx) -> list[str]:
    """Prepare template drafts, approve each exact draft, dispatch outbox (real SMTP -> Mailpit)."""
    from app.services import email as email_svc

    rec = ctx["rec"]
    r = rec.post(f"/api/hr/jobs/{ctx['job_id']}/invitation-drafts",
                 json={"application_ids": ctx["apps"], "generator": "template"})
    assert r.status_code == 201, r.text
    ids = r.json()["created"]
    for did in ids:
        d = rec.get(f"/api/hr/email-drafts/{did}").json()
        r = rec.post(f"/api/hr/email-drafts/{did}/approve-send", json={"revision": d["revision"], "digest": d["digest"]})
        assert r.status_code == 200, r.text
    while True:
        with session_scope() as db:
            if not email_svc.dispatch_once(db):
                break
    invs = []
    for did in ids:
        d = rec.get(f"/api/hr/email-drafts/{did}").json()
        invs.append(d["preview"]["link_url"].rsplit("/", 1)[-1])
    return invs


def add_slots(ctx, count: int = 3):
    from datetime import datetime, timedelta, timezone

    base = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) + timedelta(days=2)
    slots = [{"starts_at": (base + timedelta(hours=i)).isoformat(),
              "ends_at": (base + timedelta(hours=i, minutes=45)).isoformat()} for i in range(count)]
    r = ctx["rec"].post("/api/hr/slots", json={"job_id": ctx["job_id"], "slots": slots})
    assert r.status_code == 201, r.text
    return [s["id"] for s in r.json()["items"]]

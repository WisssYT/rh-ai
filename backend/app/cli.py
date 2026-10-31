"""Explicit operator commands. Nothing here runs on application startup.

  python -m app.cli seed-supervisor            # first supervisor from SUPERVISOR_EMAIL / SUPERVISOR_PASSWORD
  python -m app.cli seed-demo                  # fictional company, jobs, accounts, CVs, slots, sample states
  python -m app.cli reset-demo --yes           # wipe ALL data + uploads (refused in production)
  python -m app.cli generate-bulk --count 1000 --out ./var/bulk
  python -m app.cli import-bulk --dir ./var/bulk --job backend-developer-python
  python -m app.cli smoke-live                 # ONE tiny live Gemini call (bounded quota use)
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select, text

from .config import get_settings
from .db import Base, SessionLocal, get_engine, session_scope
from .deps import Principal, audit
from .models import Application, Company, Job, JobAssignment, RubricRevision, User, WeightsRevision, utcnow
from .security import digest, hash_password

DEMO_PASSWORD_CANDIDATE = "DemoCandidate!2026"
DEMO_PASSWORD_STAFF = "DemoStaff!2026-local"


def _refuse_production():
    if get_settings().app_env == "production":
        sys.exit("Refusing: demo seeding/reset is disabled when APP_ENV=production")


def _p(user: User) -> Principal:
    return Principal(user=user, session=None)  # type: ignore[arg-type]


# ---- rubrics -------------------------------------------------------------------------

BACKEND_CRITERIA = [
    {"id": "backend_python", "label": "Python backend development", "required": True, "weight": 30,
     "description": "Building server-side applications or services in Python (e.g. FastAPI, Django, Flask).",
     "evidence_signals": ["python", "fastapi", "django", "flask"],
     "anchors": {"0": "Evidence shows no Python backend work despite related claims",
                 "1": "Python listed as a skill only", "2": "Python backend used in projects or study",
                 "3": "Professional Python backend development", "4": "Professional Python backend work with clear scope, ownership or impact"}},
    {"id": "api_design", "label": "HTTP/REST API design", "required": False, "weight": 20,
     "description": "Designing and implementing HTTP APIs (REST/GraphQL), contracts and versioning.",
     "evidence_signals": ["api", "apis", "rest", "graphql", "openapi"],
     "anchors": {"0": "No API work", "1": "Mentions APIs only", "2": "Built APIs in projects",
                 "3": "Built production APIs professionally", "4": "Designed API contracts used by many clients"}},
    {"id": "relational_db", "label": "Relational databases & SQL", "required": True, "weight": 20,
     "description": "Designing schemas, writing SQL and operating relational databases such as PostgreSQL.",
     "evidence_signals": ["postgresql", "postgres", "sql", "mysql", "sqlite", "database"],
     "anchors": {"0": "No database work", "1": "Database listed as skill", "2": "Used a database in projects",
                 "3": "Professional schema/SQL work", "4": "Owned schemas/performance at stated scale"}},
    {"id": "testing", "label": "Automated testing", "required": False, "weight": 15,
     "description": "Writing automated unit/integration tests and keeping CI green.",
     "evidence_signals": ["pytest", "unit tests", "integration tests", "testing", "test suites", "selenium"],
     "anchors": {"0": "No testing", "1": "Testing tool listed", "2": "Tests in projects",
                 "3": "Professional automated testing", "4": "Introduced/owned a testing strategy with impact"}},
    {"id": "deployment", "label": "Containers & deployment", "required": False, "weight": 15,
     "description": "Packaging and deploying services (Docker, Kubernetes, CI/CD, Linux operations).",
     "evidence_signals": ["docker", "kubernetes", "ci/cd", "deployed", "linux", "jenkins"],
     "anchors": {"0": "No deployment work", "1": "Tool listed", "2": "Deployed a project",
                 "3": "Professional deployment work", "4": "Operated production deployments with responsibility"}},
]

ANALYST_CRITERIA = [
    {"id": "sql_analysis", "label": "SQL analysis", "required": True, "weight": 35,
     "description": "Querying relational data with SQL for analysis and reporting.",
     "evidence_signals": ["sql", "postgresql", "bigquery"],
     "anchors": {"0": "No SQL", "1": "Listed", "2": "Projects", "3": "Professional", "4": "Professional with scope/impact"}},
    {"id": "dashboards", "label": "Dashboards & BI", "required": False, "weight": 30,
     "description": "Building dashboards in tools such as Power BI or Tableau.",
     "evidence_signals": ["power bi", "tableau", "dashboards", "looker"],
     "anchors": {"0": "None", "1": "Listed", "2": "Projects", "3": "Professional", "4": "Professional with scope/impact"}},
    {"id": "statistics", "label": "Statistics", "required": False, "weight": 35,
     "description": "Applying statistical methods (testing, regression) to business questions.",
     "evidence_signals": ["statistics", "a/b test", "regression"],
     "anchors": {"0": "None", "1": "Listed", "2": "Projects/study", "3": "Professional", "4": "Professional with scope/impact"}},
]


def _approve_rubric(db, job: Job, criteria: list[dict], approver: User) -> None:
    from .services.evaluation import normalize_weights, rubric_semantics, validate_criteria

    crit = [c.model_dump() for c in validate_criteria(criteria)]
    job.criteria_draft = crit
    db.add(RubricRevision(job_id=job.id, revision=1, criteria=crit, digest=digest(rubric_semantics(crit)),
                          approved_by=approver.id))
    db.add(WeightsRevision(job_id=job.id, revision=1, rubric_revision=1,
                           weights=normalize_weights({c["id"]: c["weight"] for c in crit}), created_by=approver.id))
    job.current_rubric_revision = job.current_weights_revision = 1
    audit(db, approver, "rubric.approved", "job", job.id, job_id=job.id, revision=1, details={"seed": True})


# ---- commands ------------------------------------------------------------------------


def seed_supervisor() -> None:
    s = get_settings()
    if len(s.supervisor_password) < 12:
        sys.exit("Set SUPERVISOR_PASSWORD (min 12 chars) in the environment first")
    with session_scope() as db:
        if db.scalar(select(User).where(User.email == s.supervisor_email.lower())):
            print("Supervisor already exists - nothing changed")
            return
        u = User(email=s.supervisor_email.lower(), full_name="Company Supervisor", role="supervisor",
                 password_hash=hash_password(s.supervisor_password))
        db.add(u)
        db.flush()
        audit(db, None, "account.supervisor_seeded", "user", u.id)
    print(f"Supervisor created: {s.supervisor_email}")


def _user(db, email, name, role, password, demo=True) -> User:
    u = db.scalar(select(User).where(User.email == email))
    if u:
        return u
    u = User(email=email, full_name=name, role=role, password_hash=hash_password(password), is_demo_fixture=demo)
    db.add(u)
    db.flush()
    return u


def seed_demo() -> None:
    _refuse_production()
    from .fixtures.cvs import ANALYST_CVS, BACKEND_CVS, render_pdf
    from .services import analysis, booking, email as email_svc, ranking
    from .services.intake import check_contact, store_and_parse

    s = get_settings()
    with session_scope() as db:
        if db.scalar(select(Job).where(Job.slug == "backend-developer-python")):
            sys.exit("Demo data already present. Run `python -m app.cli reset-demo --yes` first to start over.")
        db.merge(Company(id=1, name=s.company_name, timezone=s.company_timezone,
                         contact_email="careers@nordlicht.example.test",
                         interview_instructions="The first interview takes about 45 minutes with two team members. "
                                                "No preparation is needed beyond your CV.",
                         about="Nordlicht Robotics is a fictional company that builds warehouse robots."))
        sup = _user(db, "supervisor@nordlicht.example.test", "Sara Supervisor (demo)", "supervisor", DEMO_PASSWORD_STAFF)
        rec = _user(db, "recruiter@nordlicht.example.test", "Rami Recruiter (demo)", "recruiter", DEMO_PASSWORD_STAFF)
        rec2 = _user(db, "analyst.recruiter@nordlicht.example.test", "Aya Analytics Recruiter (demo)", "recruiter",
                     DEMO_PASSWORD_STAFF)
        backend = Job(slug="backend-developer-python", title="Backend Developer (Python)", location="Tunis / hybrid",
                      summary="Build the APIs that keep our (fictional) warehouse robots moving.",
                      description="You will design, build and operate Python services and REST APIs backed by "
                                  "PostgreSQL, write automated tests and deploy with containers.\n\n"
                                  "Fictional hackathon position - do not apply with real data.",
                      status="published", published_at=utcnow(), published_by=sup.id, created_by=sup.id,
                      shortlist_size=20, min_suggest_score=45)
        analyst = Job(slug="data-analyst", title="Data Analyst", location="Remote (CET)",
                      summary="Turn robot telemetry and sales data into decisions.",
                      description="SQL-heavy analysis, dashboards and experiment statistics.\n\n"
                                  "Fictional hackathon position.",
                      status="published", published_at=utcnow() - timedelta(days=10), published_by=sup.id,
                      created_by=sup.id, shortlist_size=3, min_suggest_score=40)
        db.add_all([backend, analyst])
        db.flush()
        _approve_rubric(db, backend, BACKEND_CRITERIA, sup)
        _approve_rubric(db, analyst, ANALYST_CRITERIA, sup)
        db.add_all([JobAssignment(job_id=backend.id, user_id=rec.id, created_by=sup.id),
                     JobAssignment(job_id=analyst.id, user_id=rec2.id, created_by=sup.id)])
        audit(db, sup, "demo.seeded", "system", None, details={"fictional": True})

        def submit(cv: dict, job: Job) -> Application:
            u = _user(db, cv["email"], cv["name"], "candidate", DEMO_PASSWORD_CANDIDATE)
            pdf = render_pdf(cv["pages"], scanned=cv.get("scanned", False), title=f"CV {cv['name']}")
            doc = store_and_parse(db, u, pdf, f"{cv['key']}_cv.pdf")
            cc = check_contact(doc, u.email)
            a = Application(job_id=job.id, candidate_id=u.id, document_id=doc.id, contact_status=cc.status,
                            contact_reason=cc.reason, cv_email=cc.cv_email, storage_notice_ack=True)
            db.add(a)
            db.flush()
            audit(db, u, "application.submitted", "application", a.id, job_id=job.id, details={"seed": True})
            return a

        for cv in BACKEND_CVS:
            submit(cv, backend)
        analyst_apps = [submit(cv, analyst) for cv in ANALYST_CVS]
        # Spare candidate without an application, for the live "apply" demo step.
        _user(db, "demo.candidate@example.test", "Dana Demo-Candidate", "candidate", DEMO_PASSWORD_CANDIDATE)

        # Availability for both jobs, relative to the current date (company timezone).
        tz = s.tz
        today = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
        for job, interviewer in ((backend, rec), (analyst, rec2)):
            items = []
            for day in (2, 3, 5):
                d = today + timedelta(days=day)
                for hour in (10, 11, 14, 15):
                    st = d.replace(hour=hour)
                    items.append({"starts_at": st, "ends_at": st + timedelta(minutes=45),
                                  "location": "Video call (link sent in confirmation)"})
            booking.create_slots(db, _p(interviewer), job.id, interviewer.id, items)
        db.flush()
        analyst_id, rec2_id = analyst.id, rec2.id
        app_ids = [a.id for a in analyst_apps]

    # Pre-progressed sample workflow for the Data Analyst job (REPLAY mode, clearly labelled).
    from .services import llm

    with session_scope() as db:
        llm.set_mode(db, "replay", "seed")
    with session_scope() as db:
        rec2 = db.get(User, rec2_id)
        job = db.get(Job, analyst_id)
        analysis.authorize_run(db, _p(rec2), job, app_ids, 1)
    analysis.run_until_idle(session_scope, owner="seed")
    with session_scope() as db:
        rec2 = db.get(User, rec2_id)
        job = db.get(Job, analyst_id)
        rk = ranking.compute_ranking(db, job)
        members = [{"application_id": a} for a in rk["proposed"]]
        sl = ranking.save_shortlist_draft(db, _p(rec2), job, members)
        db.flush()
        ranking.approve_shortlist(db, _p(rec2), job, sl.id, sl.digest)
        db.flush()
        res = email_svc.prepare_invitation_drafts(db, _p(rec2), job, rk["proposed"], "template")
        db.flush()
        from .models import EmailDraft

        drafts = [db.get(EmailDraft, i) for i in res["created"]]
        # First two invitations approved by the (demo) recruiter; the rest stay as drafts for review.
        for d in drafts[:2]:
            email_svc.approve_and_send(db, _p(rec2), d.id, d.revision, email_svc.draft_digest(d, db))
    sent = 0
    for _ in range(10):
        try:
            with session_scope() as db:
                sent += email_svc.dispatch_once(db)
        except Exception as e:  # noqa: BLE001
            print(f"  (outbox dispatch skipped: {type(e).__name__}; the worker will send queued messages)")
            break
    with session_scope() as db:
        from .models import EmailDraft, Invitation, InterviewSlot

        invs = list(db.scalars(select(Invitation).where(Invitation.job_id == analyst_id, Invitation.status == "sent")))
        slots = list(db.scalars(select(InterviewSlot).where(InterviewSlot.job_id == analyst_id,
                                                            InterviewSlot.status == "available")
                                .order_by(InterviewSlot.starts_at)))
        rec2 = db.get(User, rec2_id)
        for i, inv in enumerate(invs[:2]):
            cand = db.get(User, inv.candidate_id)
            br, _ = booking.request_slot(db, _p(cand), inv.id, slots[i].id, f"seed-{inv.id[:12]}")
            db.flush()
            if i == 0:
                booking.decide(db, _p(rec2), br, "confirm")
                db.flush()
                from .models import Interview

                iv = db.scalar(select(Interview).where(Interview.booking_id == br.id))
                email_svc.prepare_confirmation_draft(db, _p(rec2), iv)
    print("Demo data seeded (fictional). Accounts:")
    print("  supervisor@nordlicht.example.test / recruiter@nordlicht.example.test /"
          f" analyst.recruiter@nordlicht.example.test  password: {DEMO_PASSWORD_STAFF}")
    print(f"  candidates: amira.bensalah@example.test, demo.candidate@example.test, ...  password: {DEMO_PASSWORD_CANDIDATE}")
    print(f"  AI mode set to REPLAY for seeding; switch explicitly in /supervisor. Emails dispatched now: {sent}")


def reset_demo(yes: bool) -> None:
    _refuse_production()
    if not yes:
        sys.exit("This deletes ALL data and uploaded files. Re-run with --yes to confirm.")
    eng = get_engine()
    with eng.begin() as conn:
        names = ", ".join(f'"{t.name}"' for t in reversed(Base.metadata.sorted_tables))
        conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
    up = get_settings().upload_path
    for child in up.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    print("All data and uploads removed.")


# ---- bulk ----------------------------------------------------------------------------

FIRST = ["Adam", "Lina", "Noah", "Sami", "Yara", "Elias", "Mia", "Omar", "Nour", "Lukas", "Selma", "Theo", "Rim",
         "Ilyes", "Zoe", "Malek", "Hedi", "Anya", "Bilal", "Clea", "Dario", "Emna", "Fares", "Greta"]
LAST = ["Arfaoui", "Berger", "Chaabane", "Dubois", "Engel", "Ferjani", "Garcia", "Hamdi", "Ivanova", "Jebali",
        "Keller", "Lahmar", "Meyer", "Nasri", "Ortiz", "Pohl", "Quinn", "Riahi", "Sauer", "Toumi"]
ROLES = ["Backend Developer", "Software Engineer", "Data Engineer", "DevOps Engineer", "QA Engineer",
         "Frontend Developer", "Full-stack Developer", "IT Support Specialist", "Data Analyst", "Java Developer"]
COMPANIES = ["Atlas Freight", "Blue Dune Labs", "Cobalt Retail", "Delta Grid", "Ember Health", "Fjord Media",
             "Granite Bank", "Helix Games", "Iris Travel", "Juniper Energy"]
STACK = {
    "python": ["Developed Python services with FastAPI", "Built Django REST endpoints", "Wrote Python automation scripts",
               "Maintained a Flask API"],
    "api": ["Designed REST APIs with OpenAPI contracts for {n} clients", "Implemented GraphQL endpoints",
            "Integrated third-party REST APIs"],
    "db": ["Designed PostgreSQL schemas and tuned SQL queries", "Wrote SQL reports on MySQL",
           "Migrated data between PostgreSQL databases"],
    "test": ["Wrote pytest integration tests and kept CI green", "Built Selenium test suites",
             "Introduced unit testing for a legacy codebase"],
    "ops": ["Deployed services with Docker and Kubernetes", "Maintained CI/CD pipelines in Jenkins",
            "Operated Linux servers in production"],
    "other": ["Built React dashboards", "Supported 300 office users", "Created Tableau dashboards",
              "Developed Java Spring Boot services"],
}


def _bulk_cv(i: int, rng: random.Random) -> dict:
    first, last = rng.choice(FIRST), rng.choice(LAST)
    name = f"{first} {last}"
    email = f"bulk{i:04d}.{first.lower()}@bulk.example.test"
    lines = [name, email, "", "EXPERIENCE"]
    year = rng.randint(2012, 2021)
    for _ in range(rng.randint(1, 3)):
        end = min(2025, year + rng.randint(1, 4))
        lines.append(f"{rng.choice(ROLES)}, {rng.choice(COMPANIES)} (fictional), {year} - {end}")
        for area in rng.sample(list(STACK), k=rng.randint(1, 4)):
            lines.append(rng.choice(STACK[area]).format(n=rng.randint(2, 60)) + ".")
        year = end
    skills = rng.sample(["Python", "FastAPI", "Django", "PostgreSQL", "SQL", "Docker", "Kubernetes", "pytest", "Java",
                         "React", "Go", "Excel", "Linux", "Terraform"], k=rng.randint(2, 7))
    lines += ["", "SKILLS", "Skills: " + ", ".join(skills)]
    return {"name": name, "email": email, "pages": [lines]}


def generate_bulk(count: int, out: str, seed: int = 7) -> None:
    from .fixtures.cvs import render_pdf

    _refuse_production()
    rng = random.Random(seed)
    d = Path(out)
    d.mkdir(parents=True, exist_ok=True)
    manifest = []
    t0 = time.perf_counter()
    for i in range(1, count + 1):
        cv = _bulk_cv(i, rng)
        fn = f"bulk_{i:04d}.pdf"
        (d / fn).write_bytes(render_pdf(cv["pages"], title=f"CV {cv['name']}"))
        manifest.append({"file": fn, "name": cv["name"], "email": cv["email"]})
    (d / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print(f"Generated {count} fictional PDFs in {d} ({time.perf_counter() - t0:.1f}s)")


def import_bulk(directory: str, job_slug: str) -> dict:
    from .services.intake import check_contact, store_and_parse

    _refuse_production()
    d = Path(directory)
    manifest = json.loads((d / "manifest.json").read_text())
    pw = hash_password(DEMO_PASSWORD_CANDIDATE)  # one hash reused for speed; fixture accounts only
    t0 = time.perf_counter()
    n = 0
    with session_scope() as db:
        job = db.scalar(select(Job).where(Job.slug == job_slug))
        if job is None:
            sys.exit(f"Job {job_slug} not found")
        job_id = job.id
    for i in range(0, len(manifest), 50):
        with session_scope() as db:
            for m in manifest[i:i + 50]:
                u = db.scalar(select(User).where(User.email == m["email"]))
                if u is None:
                    u = User(email=m["email"], full_name=m["name"], role="candidate", password_hash=pw,
                             is_demo_fixture=True)
                    db.add(u)
                    db.flush()
                elif db.scalar(select(Application).where(Application.candidate_id == u.id,
                                                         Application.job_id == job_id)):
                    continue
                doc = store_and_parse(db, u, (d / m["file"]).read_bytes(), m["file"])
                cc = check_contact(doc, u.email)
                db.add(Application(job_id=job_id, candidate_id=u.id, document_id=doc.id, contact_status=cc.status,
                                   contact_reason=cc.reason, cv_email=cc.cv_email, storage_notice_ack=True))
                n += 1
    dt = time.perf_counter() - t0
    print(f"Imported {n} applications in {dt:.1f}s ({n / dt if dt else 0:.1f}/s)")
    return {"imported": n, "seconds": dt}


def smoke_live() -> None:
    """One deliberately tiny live request to confirm the configured free-tier model answers."""
    from .services.evaluation import DraftOutput
    from .services.llm.base import DraftRequest
    from .services.llm.gemini import GeminiProvider

    s = get_settings()
    if not s.live_ai_configured:
        sys.exit("GEMINI_API_KEY is not set")
    p = GeminiProvider()
    req = DraftRequest(system_prompt="Return JSON with a short subject and body greeting a fictional person.",
                       user_prompt='{"name": "Test Person (fictional)"}',
                       response_schema=DraftOutput.model_json_schema())
    r = p.draft_invitation(req)
    from .models import AICallLog

    with session_scope() as db:
        db.add(AICallLog(purpose="smoke", mode="live", model_id=r.model_id, outcome="ok", latency_ms=r.latency_ms,
                         prompt_tokens=r.usage.prompt_tokens, cached_tokens=r.usage.cached_tokens,
                         output_tokens=r.usage.output_tokens, thinking_tokens=r.usage.thinking_tokens,
                         usage_reported=r.usage.reported))
    print(json.dumps({"model": r.model_id, "latency_ms": r.latency_ms, "usage": r.usage.__dict__,
                      "output_preview": r.text[:200]}, indent=2))


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m app.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("seed-supervisor")
    sub.add_parser("seed-demo")
    r = sub.add_parser("reset-demo")
    r.add_argument("--yes", action="store_true")
    g = sub.add_parser("generate-bulk")
    g.add_argument("--count", type=int, default=1000)
    g.add_argument("--out", default="./var/bulk")
    i = sub.add_parser("import-bulk")
    i.add_argument("--dir", default="./var/bulk")
    i.add_argument("--job", default="backend-developer-python")
    sub.add_parser("smoke-live")
    a = ap.parse_args(argv)
    {"seed-supervisor": seed_supervisor, "seed-demo": seed_demo, "smoke-live": smoke_live}.get(a.cmd, lambda: None)()
    if a.cmd == "reset-demo":
        reset_demo(a.yes)
    elif a.cmd == "generate-bulk":
        generate_bulk(a.count, a.out)
    elif a.cmd == "import-bulk":
        import_bulk(a.dir, a.job)


if __name__ == "__main__":
    main()

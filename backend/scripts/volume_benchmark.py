"""1,000-application intake + REPLAY analysis benchmark.

Measures real PDF generation, safe intake (signature checks + isolated subprocess parsing + storage),
durable task processing in REPLAY mode, saved-evaluation reuse, ranking and paginated listing.
This is NOT a test of 1,000 live LLM evaluations - no provider is called.

Usage (uses its own database; never point it at demo data):
  VOLUME_DATABASE_URL=postgresql+psycopg://...@localhost:55432/talent_volume \
    .venv/bin/python scripts/volume_benchmark.py --count 1000
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ap = argparse.ArgumentParser()
ap.add_argument("--count", type=int, default=1000)
ap.add_argument("--out", default=None)
args = ap.parse_args()

os.environ["DATABASE_URL"] = os.environ.get("VOLUME_DATABASE_URL",
                                            "postgresql+psycopg://postgres@localhost:55432/talent_volume")
os.environ["APP_ENV"] = "development"
os.environ["AI_MODE"] = "replay"
os.environ["UPLOAD_DIR"] = tempfile.mkdtemp(prefix="td-volume-")

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import func, select, text  # noqa: E402

from app import cli  # noqa: E402
from app.db import get_engine, session_scope  # noqa: E402
from app.deps import Principal  # noqa: E402
from app.models import AnalysisTask, Application, Company, Job, JobAssignment, User  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.services import analysis, llm, ranking  # noqa: E402

root = Path(__file__).resolve().parents[1]
with get_engine().begin() as c:
    c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
cfg = Config(str(root / "alembic.ini"))
cfg.set_main_option("script_location", str(root / "alembic"))
command.upgrade(cfg, "head")

results: dict = {"count": args.count, "mode": "replay (synthetic deterministic adapter - no LLM calls)",
                 "python": platform.python_version(), "cpu_count": os.cpu_count(), "platform": platform.platform()}

with session_scope() as db:
    db.add(Company(id=1, name="Volume Co (fictional)", timezone="Africa/Tunis", contact_email="hr@example.test"))
    sup = User(email="vol-sup@example.test", full_name="Vol Sup", role="supervisor", password_hash=hash_password("x" * 16))
    rec = User(email="vol-rec@example.test", full_name="Vol Rec", role="recruiter", password_hash=hash_password("Volume-Rec-Pw-1"))
    db.add_all([sup, rec])
    db.flush()
    job = Job(slug="backend-developer-python", title="Backend Developer", description="Python APIs", status="published",
              created_by=sup.id, shortlist_size=20, min_suggest_score=45)
    db.add(job)
    db.flush()
    cli._approve_rubric(db, job, cli.BACKEND_CRITERIA, sup)
    db.add(JobAssignment(job_id=job.id, user_id=rec.id))
    llm.set_mode(db, "replay", sup.id)
    job_id, rec_id = job.id, rec.id

bulk_dir = tempfile.mkdtemp(prefix="td-bulk-")
t = time.perf_counter()
cli.generate_bulk(args.count, bulk_dir)
results["generate_pdfs_s"] = round(time.perf_counter() - t, 2)

t = time.perf_counter()
imp = cli.import_bulk(bulk_dir, "backend-developer-python")
results["intake_s"] = round(time.perf_counter() - t, 2)
results["intake_per_application_ms"] = round(1000 * results["intake_s"] / max(1, imp["imported"]), 1)

with session_scope() as db:
    ids = list(db.scalars(select(Application.id).where(Application.job_id == job_id)))
    results["applications"] = len(ids)
    results["parse_needs_review"] = db.scalar(
        select(func.count()).select_from(Application).join(Application.document)
        .where(Application.job_id == job_id).where(text("resume_documents.parse_status <> 'parsed'")))
    rec = db.get(User, rec_id)
    analysis.authorize_run(db, Principal(rec, None), db.get(Job, job_id), ids, 1)

t = time.perf_counter()
n = analysis.run_until_idle(session_scope, owner="volume")
results["replay_analysis_s"] = round(time.perf_counter() - t, 2)
results["replay_tasks_processed"] = n

with session_scope() as db:
    for r in db.scalars(select(analysis.AnalysisRun)):
        r.status = "completed"
    rec = db.get(User, rec_id)
    analysis.authorize_run(db, Principal(rec, None), db.get(Job, job_id), ids, 1)
t = time.perf_counter()
analysis.run_until_idle(session_scope, owner="volume-2")
results["second_run_saved_evaluation_reuse_s"] = round(time.perf_counter() - t, 2)
with session_scope() as db:
    results["second_run_reused"] = db.scalar(select(func.count(AnalysisTask.id))
                                             .where(AnalysisTask.result_source == "saved_evaluation"))

with session_scope() as db:
    t = time.perf_counter()
    rk = ranking.compute_ranking(db, db.get(Job, job_id))
    results["ranking_s"] = round(time.perf_counter() - t, 2)
    results["proposed"] = len(rk["proposed"])
    results["review_list"] = len(rk["review"])
    t = time.perf_counter()
    rk2 = ranking.compute_ranking(db, db.get(Job, job_id), weights_override={c["id"]: 20 for c in rk["criteria"]})
    results["reweight_preview_s"] = round(time.perf_counter() - t, 2)
    results["reweight_llm_calls"] = rk2["llm_calls"]

from app.main import app  # noqa: E402

c = TestClient(app)
csrf = c.get("/api/auth/csrf").json()["csrf_token"]
c.post("/api/auth/login", json={"email": "vol-rec@example.test", "password": "Volume-Rec-Pw-1", "portal": "staff"},
       headers={"x-csrf-token": csrf})
t = time.perf_counter()
r = c.get(f"/api/hr/jobs/{job_id}/applications?page=20&page_size=25")
results["api_list_page_ms"] = round(1000 * (time.perf_counter() - t), 1)
results["api_list_total"] = r.json()["total"]

print(json.dumps(results, indent=2))
if args.out:
    Path(args.out).write_text(json.dumps(results, indent=2) + "\n")

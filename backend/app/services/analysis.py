"""Analysis runs: explicit authorization, durable leased tasks, saved-evaluation reuse, quota pausing."""

from __future__ import annotations

import random
import time
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from ..config import get_settings
from ..deps import Principal, audit
from ..models import (
    AICallLog,
    AnalysisRun,
    AnalysisTask,
    Application,
    Approval,
    Evaluation,
    Job,
    RubricRevision,
    User,
    utcnow,
)
from ..security import digest
from . import llm
from .evaluation import (
    PROMPT_VERSION,
    OutputInvalid,
    build_shared_prefix,
    build_variable_part,
    parse_and_validate,
    rubric_semantics,
    screening_json_schema,
)
from .llm.base import ProviderError, QuotaExceeded, ScreeningRequest
from .text_tools import detect_injection, redact_pages

LEASE_SECONDS = 180
ACTIVE_RUN_STATES = ("queued", "running")


def current_rubric(db: Session, job: Job) -> RubricRevision | None:
    if job.current_rubric_revision is None:
        return None
    return db.scalar(
        select(RubricRevision).where(
            RubricRevision.job_id == job.id, RubricRevision.revision == job.current_rubric_revision
        )
    )


def gen_config() -> dict:
    s = get_settings()
    return {"temperature": s.ai_temperature, "max_output_tokens": s.ai_max_output_tokens}


def dependency_key(app: Application, rubric: RubricRevision, provider: str, model_id: str) -> str:
    """Everything that can change criterion interpretation. Weights are deliberately excluded."""
    return digest(
        {
            "application_id": app.id,
            "application_revision": app.revision,
            "document_sha256": app.document.sha256,
            "parser_version": app.document.parser_version,
            "rubric_digest": rubric.digest,
            "prompt_version": PROMPT_VERSION,
            "provider": provider,
            "model": model_id,
            "gen": gen_config(),
        }
    )


# ---- authorization -----------------------------------------------------------------


def authorize_run(
    db: Session, p: Principal, job: Job, application_ids: list[str], rubric_revision: int
) -> AnalysisRun:
    s = get_settings()
    rubric = current_rubric(db, job)
    if rubric is None:
        raise HTTPException(409, "The job has no approved rubric yet - approve the rubric first")
    if rubric.revision != rubric_revision:
        raise HTTPException(409, "Stale rubric revision: the rubric changed since you reviewed it")
    ids = sorted(set(application_ids))
    if not ids:
        raise HTTPException(422, "Select at least one application")
    if len(ids) > 2000:
        raise HTTPException(422, "Too many applications in one run")
    found = set(
        db.scalars(
            select(Application.id).where(
                Application.id.in_(ids), Application.job_id == job.id, Application.status == "submitted"
            )
        )
    )
    if found != set(ids):
        raise HTTPException(422, "Some selected applications do not belong to this job or are withdrawn")

    active = db.scalar(
        select(func.count(AnalysisRun.id)).where(
            AnalysisRun.job_id == job.id, AnalysisRun.status.in_(ACTIVE_RUN_STATES + ("quota_paused",))
        )
    )
    if active:
        raise HTTPException(409, "Another analysis run for this job is still active or paused")
    recent = db.scalar(
        select(func.count(AnalysisRun.id)).where(
            AnalysisRun.authorized_by == p.id, AnalysisRun.authorized_at >= utcnow() - timedelta(hours=1)
        )
    )
    if recent >= s.analysis_runs_per_hour:
        raise HTTPException(429, "Analysis run limit reached for this hour")

    mode = llm.current_mode(db)
    if mode == "live" and not s.live_ai_configured and llm._provider_override is None:
        raise HTTPException(
            409,
            "Live AI mode is selected but GEMINI_API_KEY is not configured. "
            "A supervisor can explicitly switch to replay mode.",
        )
    provider, model_id = llm.model_id_for_mode(mode)
    scope = {"job_id": job.id, "rubric_digest": rubric.digest, "application_ids": ids, "mode": mode}
    run = AnalysisRun(
        job_id=job.id,
        rubric_revision=rubric.revision,
        rubric_digest=rubric.digest,
        application_ids=ids,
        scope_digest=digest(scope),
        mode=mode,
        provider=provider,
        model_id=model_id,
        prompt_version=PROMPT_VERSION,
        status="queued",
        authorized_by=p.id,
        authorized_role=p.role,
    )
    db.add(run)
    db.flush()
    for aid in ids:
        db.add(AnalysisTask(run_id=run.id, application_id=aid))
    db.add(
        Approval(
            action="authorize_analysis_run",
            target_type="analysis_run",
            target_id=run.id,
            target_revision=rubric.revision,
            digest=run.scope_digest,
            approver_id=p.id,
            approver_role=p.role,
        )
    )
    audit(db, p, "analysis.authorized", "analysis_run", run.id, job_id=job.id, revision=rubric.revision,
          digest=run.scope_digest, details={"applications": len(ids), "mode": mode, "model": model_id})
    return run


# ---- worker side -------------------------------------------------------------------


def recover_expired_leases(db: Session) -> int:
    res = db.execute(
        update(AnalysisTask)
        .where(AnalysisTask.status == "running", AnalysisTask.lease_until < utcnow())
        .values(status="queued", lease_owner=None, lease_until=None, updated_at=utcnow())
    )
    return res.rowcount or 0


def claim_tasks(db: Session, owner: str, n: int) -> list[str]:
    rows = db.execute(
        text(
            """
            UPDATE analysis_tasks SET status='running', lease_owner=:owner,
                   lease_until=now() + make_interval(secs => :lease), attempts = attempts + 1, updated_at=now()
            WHERE id IN (
              SELECT t.id FROM analysis_tasks t JOIN analysis_runs r ON r.id = t.run_id
              WHERE t.status='queued' AND r.status IN ('queued','running')
                AND (t.not_before IS NULL OR t.not_before <= now())
              ORDER BY t.created_at, t.id
              FOR UPDATE OF t SKIP LOCKED LIMIT :n)
            RETURNING id, run_id
            """
        ),
        {"owner": owner, "lease": LEASE_SECONDS, "n": n},
    ).all()
    run_ids = {r.run_id for r in rows}
    if run_ids:
        db.execute(
            update(AnalysisRun)
            .where(AnalysisRun.id.in_(run_ids), AnalysisRun.status == "queued")
            .values(status="running")
        )
    db.commit()
    return [r.id for r in rows]


def _log_call(db: Session, run: AnalysisRun, task: AnalysisTask, outcome: str, resp=None, latency=0) -> None:
    u = resp.usage if resp is not None else None
    db.add(
        AICallLog(
            purpose="screening",
            mode=run.mode,
            model_id=(resp.model_id if resp is not None else run.model_id),
            run_id=run.id,
            task_id=task.id,
            outcome=outcome,
            latency_ms=(resp.latency_ms if resp is not None else latency),
            prompt_tokens=u.prompt_tokens if u else None,
            cached_tokens=u.cached_tokens if u else None,
            output_tokens=u.output_tokens if u else None,
            thinking_tokens=u.thinking_tokens if u else None,
            usage_reported=bool(u and u.reported),
        )
    )


def _name_hints(app: Application) -> list[str]:
    names = [app.candidate.full_name]
    pages = app.document.pages or []
    if pages and pages[0]["segments"]:
        first = pages[0]["segments"][0]["text"]
        words = first.split()
        if 1 < len(words) <= 4 and not any(ch.isdigit() for ch in first):
            names.append(first)
    return names


def _store_evaluation(
    db: Session, run: AnalysisRun, app: Application, dep_key: str, result: dict, source: str,
    flags: list[str], errors: list[str], state: str,
) -> Evaluation:
    db.execute(
        update(Evaluation)
        .where(Evaluation.application_id == app.id, Evaluation.review_state != "superseded")
        .values(review_state="superseded")
    )
    ev = Evaluation(
        application_id=app.id,
        job_id=app.job_id,
        run_id=run.id,
        dependency_key=dep_key,
        rubric_revision=run.rubric_revision,
        document_sha256=app.document.sha256,
        provider=run.provider,
        model_id=run.model_id,
        prompt_version=run.prompt_version,
        source=source,
        review_state=state,
        result=result,
        review_flags=sorted(set(flags)),
        validation_errors=errors,
    )
    db.add(ev)
    db.flush()
    return ev


def process_task(db: Session, task_id: str) -> str:
    """Execute one approved task. Returns the final task status."""
    s = get_settings()
    task = db.get(AnalysisTask, task_id, with_for_update=True)
    if task is None or task.status != "running":
        return "skipped"
    run = db.get(AnalysisRun, task.run_id)
    if run.status not in ACTIVE_RUN_STATES:
        task.status = "cancelled" if run.status == "cancelled" else "queued"
        task.lease_owner = task.lease_until = None
        db.commit()
        return task.status
    # The worker only executes work inside the approved scope.
    if task.application_id not in run.application_ids:
        task.status, task.last_error = "failed", "task outside authorized scope"
        db.commit()
        return task.status
    app = db.get(Application, task.application_id)
    rubric = db.scalar(
        select(RubricRevision).where(RubricRevision.job_id == run.job_id,
                                     RubricRevision.revision == run.rubric_revision)
    )
    if rubric is None or rubric.digest != run.rubric_digest:
        task.status, task.last_error = "failed", "rubric changed after authorization"
        db.commit()
        return task.status
    job = db.get(Job, run.job_id)
    criteria = rubric.criteria
    dep_key = dependency_key(app, rubric, run.provider, run.model_id)

    # Application-result cache (PostgreSQL): reuse a saved evaluation with identical dependencies.
    saved = db.scalar(
        select(Evaluation)
        .where(Evaluation.dependency_key == dep_key, Evaluation.application_id == app.id,
               Evaluation.review_state.in_(("provisional", "needs_review")))
        .order_by(Evaluation.created_at.desc())
    )
    if saved is not None:
        task.status, task.evaluation_id, task.result_source = "done", saved.id, "saved_evaluation"
        task.usage = {"llm_calls": 0, "reused_evaluation": saved.id}
        _finish(db, task)
        return task.status

    doc = app.document
    redacted = redact_pages(doc.pages or [], _name_hints(app))
    parse_flags = list(doc.parse_flags or [])
    has_text = sum(len(sg["text"]) for p in redacted for sg in p["segments"]) >= 50
    if not has_text:
        result = {
            "application_ref": app.id,
            "criteria": [
                {"criterion_id": c["id"], "status": "unknown", "rating": None, "evidence": [],
                 "explanation": "Not assessed: no usable text was extracted.", "unknowns": ["CV text unavailable"]}
                for c in criteria
            ],
            "review_flags": ["no_extracted_text_manual_review"],
            "job_related_summary": "Manual review required: the document could not be read automatically.",
        }
        ev = _store_evaluation(db, run, app, dep_key, result, "system", parse_flags + result["review_flags"], [],
                               "needs_review")
        task.status, task.evaluation_id, task.result_source = "needs_review", ev.id, "no_text"
        task.usage = {"llm_calls": 0}
        _finish(db, task)
        return task.status

    req = ScreeningRequest(
        system_prompt=build_shared_prefix(job.title, job.description, criteria),
        user_prompt=build_variable_part(app.id, redacted),
        response_schema=screening_json_schema(),
        application_ref=app.id,
        criteria=criteria,
        redacted_pages=redacted,
    )
    try:
        provider = llm.provider_for_mode(run.mode)
    except ProviderError as e:
        return _pause(db, run, task, f"live provider unavailable: {e}")

    injection_hits = detect_injection(" ".join(sg["text"] for p in redacted for sg in p["segments"]))
    calls, quota_hits, last_errors = 0, 0, []
    usage_acc = {"llm_calls": 0, "prompt_tokens": None, "cached_tokens": None, "output_tokens": None,
                 "thinking_tokens": None, "usage_reported": False, "latency_ms": 0, "retries": 0}
    max_invalid = s.ai_max_retries + 1
    while True:
        try:
            llm.check_daily_budget(db, run.mode)
            if run.mode == "live":
                llm.rpm_limiter.wait()
            calls += 1
            resp = provider.evaluate_resume(req)
        except QuotaExceeded as e:
            _log_call(db, run, task, "quota")
            quota_hits += 1
            if isinstance(e, llm.DailyBudgetExhausted) or quota_hits > s.ai_quota_retries:
                return _pause(db, run, task, str(e), retry_after=e.retry_after)
            delay = min(30.0, (e.retry_after or 2 ** quota_hits)) + random.uniform(0, 0.5)
            db.commit()
            time.sleep(delay if run.mode == "live" else 0)
            usage_acc["retries"] += 1
            continue
        except ProviderError as e:
            _log_call(db, run, task, "error")
            last_errors = [str(e)]
            if calls >= max_invalid:
                break
            usage_acc["retries"] += 1
            continue
        usage_acc["llm_calls"] += 1
        usage_acc["latency_ms"] += resp.latency_ms
        if resp.usage.reported:
            usage_acc["usage_reported"] = True
            for k in ("prompt_tokens", "cached_tokens", "output_tokens", "thinking_tokens"):
                v = getattr(resp.usage, k)
                if v is not None:
                    usage_acc[k] = (usage_acc[k] or 0) + v
        usage_acc["model_id"] = resp.model_id
        try:
            out = parse_and_validate(resp.text, application_ref=app.id, criteria=criteria, redacted_pages=redacted)
        except OutputInvalid as e:
            _log_call(db, run, task, "invalid_output", resp)
            last_errors = e.errors
            if calls >= max_invalid:
                break
            usage_acc["retries"] += 1
            continue
        _log_call(db, run, task, "ok", resp)
        result = out.model_dump()
        flags = list(out.review_flags) + parse_flags
        if injection_hits:
            flags.append("possible_prompt_injection")
        for c in criteria:
            cr = next(r for r in out.criteria if r.criterion_id == c["id"])
            if c.get("required") and cr.status == "unknown":
                flags.append(f"required_criterion_unknown:{c['id']}")
        state = "needs_review" if flags else "provisional"
        ev = _store_evaluation(db, run, app, dep_key, result, run.mode, flags, [], state)
        task.status = "needs_review" if state == "needs_review" else "done"
        task.evaluation_id, task.result_source, task.usage = ev.id, run.mode, usage_acc
        _finish(db, task)
        return task.status

    # Retry budget exhausted: keep the case visible for human review; never invent a result.
    result = {"application_ref": app.id, "criteria": [], "review_flags": ["invalid_model_output"],
              "job_related_summary": ""}
    ev = _store_evaluation(db, run, app, dep_key, result, run.mode, ["invalid_model_output"], last_errors[:10],
                           "invalid")
    task.status, task.evaluation_id, task.result_source = "needs_review", ev.id, run.mode
    task.last_error = "; ".join(last_errors)[:2000]
    task.usage = usage_acc
    _finish(db, task)
    return task.status


def _pause(db: Session, run: AnalysisRun, task: AnalysisTask, reason: str, retry_after: float | None = None) -> str:
    task.status = "queued"
    task.lease_owner = task.lease_until = None
    task.attempts = max(0, task.attempts - 1)
    task.last_error = reason[:500]
    task.updated_at = utcnow()
    run.status = "quota_paused"
    run.pause_reason = reason[:300]
    audit(db, None, "analysis.paused", "analysis_run", run.id, job_id=run.job_id, outcome="paused",
          details={"reason": reason[:200], "retry_after_s": retry_after})
    db.commit()
    return "quota_paused"


def _finish(db: Session, task: AnalysisTask) -> None:
    task.lease_owner = task.lease_until = None
    task.updated_at = utcnow()
    db.flush()
    run = db.get(AnalysisRun, task.run_id, with_for_update=True)
    remaining = db.scalar(
        select(func.count(AnalysisTask.id)).where(
            AnalysisTask.run_id == run.id, AnalysisTask.status.in_(("queued", "running"))
        )
    )
    if remaining == 0 and run.status in ACTIVE_RUN_STATES:
        problems = db.scalar(
            select(func.count(AnalysisTask.id)).where(
                AnalysisTask.run_id == run.id, AnalysisTask.status.in_(("needs_review", "failed"))
            )
        )
        run.status = "completed_with_review" if problems else "completed"
        run.finished_at = utcnow()
        audit(db, None, "analysis.finished", "analysis_run", run.id, job_id=run.job_id, outcome=run.status)
    db.commit()


def run_until_idle(db_factory, owner: str = "inline", max_tasks: int = 100000) -> int:
    """Process queued tasks synchronously (tests, CLI, volume benchmark)."""
    done = 0
    while done < max_tasks:
        with db_factory() as db:
            recover_expired_leases(db)
            db.commit()
            ids = claim_tasks(db, owner, 10)
        if not ids:
            break
        for tid in ids:
            with db_factory() as db:
                process_task(db, tid)
            done += 1
    return done


# ---- HR controls -------------------------------------------------------------------


def set_run_state(db: Session, p: Principal, run: AnalysisRun, action: str) -> AnalysisRun:
    if action == "pause":
        if run.status not in ACTIVE_RUN_STATES:
            raise HTTPException(409, f"Cannot pause a run in state {run.status}")
        run.status, run.pause_reason = "quota_paused", "paused by recruiter"
    elif action == "resume":
        if run.status != "quota_paused":
            raise HTTPException(409, f"Cannot resume a run in state {run.status}")
        if run.mode == "live" and not get_settings().live_ai_configured and llm._provider_override is None:
            raise HTTPException(409, "Live mode is unavailable (no API key); the run stays paused")
        run.status, run.pause_reason = "queued", ""
        db.execute(update(AnalysisTask).where(AnalysisTask.run_id == run.id, AnalysisTask.status == "queued")
                   .values(not_before=None))
    elif action == "cancel":
        if run.status not in ACTIVE_RUN_STATES + ("quota_paused",):
            raise HTTPException(409, f"Cannot cancel a run in state {run.status}")
        run.status, run.finished_at = "cancelled", utcnow()
        db.execute(update(AnalysisTask).where(AnalysisTask.run_id == run.id, AnalysisTask.status == "queued")
                   .values(status="cancelled"))
    else:
        raise HTTPException(422, "Unknown action")
    audit(db, p, f"analysis.{action}", "analysis_run", run.id, job_id=run.job_id)
    return run


def run_summary(db: Session, run: AnalysisRun) -> dict:
    counts = dict(
        db.execute(
            select(AnalysisTask.status, func.count()).where(AnalysisTask.run_id == run.id)
            .group_by(AnalysisTask.status)
        ).all()
    )
    sources = dict(
        db.execute(
            select(AnalysisTask.result_source, func.count()).where(
                AnalysisTask.run_id == run.id, AnalysisTask.result_source.is_not(None))
            .group_by(AnalysisTask.result_source)
        ).all()
    )
    calls = db.execute(
        select(
            func.count(AICallLog.id),
            func.count(AICallLog.id).filter(AICallLog.outcome == "ok"),
            func.count(AICallLog.id).filter(AICallLog.outcome == "invalid_output"),
            func.count(AICallLog.id).filter(AICallLog.outcome == "quota"),
            func.count(AICallLog.id).filter(AICallLog.usage_reported.is_(True)),
            func.sum(AICallLog.prompt_tokens),
            func.sum(AICallLog.cached_tokens),
            func.count(AICallLog.cached_tokens),
            func.sum(AICallLog.output_tokens),
            func.sum(AICallLog.thinking_tokens),
            func.avg(AICallLog.latency_ms),
        ).where(AICallLog.run_id == run.id)
    ).one()
    authorized_by = db.get(User, run.authorized_by)
    return {
        "id": run.id,
        "job_id": run.job_id,
        "status": run.status,
        "pause_reason": run.pause_reason,
        "mode": run.mode,
        "provider": run.provider,
        "model_id": run.model_id,
        "prompt_version": run.prompt_version,
        "rubric_revision": run.rubric_revision,
        "application_count": len(run.application_ids),
        "authorized_by": authorized_by.full_name if authorized_by else None,
        "authorized_role": run.authorized_role,
        "authorized_at": run.authorized_at,
        "finished_at": run.finished_at,
        "tasks": counts,
        "result_sources": sources,
        "usage": {
            "provider_attempts": calls[0] if run.mode == "live" else 0,
            "replay_generations": calls[0] if run.mode == "replay" else 0,
            "ok": calls[1],
            "invalid_output": calls[2],
            "quota_responses": calls[3],
            "usage_reported_calls": calls[4],
            "prompt_tokens": calls[5],
            # provider prefix-cache reuse: sum only over calls whose metadata contained the field
            "cached_tokens": calls[6],
            "cached_tokens_reported_calls": calls[7],
            "output_tokens": calls[8],
            "thinking_tokens": calls[9],
            "avg_latency_ms": round(calls[10]) if calls[10] is not None else None,
            "saved_evaluation_reuse": sources.get("saved_evaluation", 0),
        },
    }

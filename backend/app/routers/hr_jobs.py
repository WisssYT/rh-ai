"""HR: jobs, rubric/weights, applications, analysis runs, ranking and shortlists."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import (
    Principal,
    assigned_job_ids,
    audit,
    get_application_for_staff,
    get_job_for_staff,
    limit,
    require_staff,
)
from ..models import (
    AnalysisRun,
    Application,
    Evaluation,
    Job,
    JobAssignment,
    ResumeDocument,
    RubricRevision,
    Shortlist,
    User,
    WeightsRevision,
    utcnow,
)
from ..security import digest
from ..services import analysis as analysis_svc
from ..services import llm
from ..services import ranking as ranking_svc
from ..services.evaluation import normalize_weights, rubric_semantics, validate_criteria
from .candidate import pdf_response
from ..services.intake import resume_path

router = APIRouter(prefix="/api/hr", tags=["hr"])


# ---- jobs & rubric -------------------------------------------------------------------


class JobIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=3, max_length=200)
    location: str = Field(default="", max_length=200)
    employment_type: str = Field(default="Full-time", max_length=60)
    summary: str = Field(default="", max_length=600)
    description: str = Field(default="", max_length=8000)
    criteria_draft: list[dict] = Field(default_factory=list, max_length=12)


class JobSettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    shortlist_size: int = Field(ge=1, le=200)
    min_suggest_score: int = Field(ge=0, le=100)


def _criteria_digest(criteria: list[dict]) -> str:
    return digest(criteria)


def job_staff_out(db: Session, j: Job) -> dict:
    rubric = analysis_svc.current_rubric(db, j)
    wrev = ranking_svc.current_weights(db, j)
    counts = db.execute(
        select(func.count(Application.id),
               func.count(Application.id).filter(Application.contact_status != "ok"))
        .where(Application.job_id == j.id, Application.status == "submitted")
    ).one()
    assignees = db.execute(select(User.id, User.full_name).join(JobAssignment, JobAssignment.user_id == User.id)
                           .where(JobAssignment.job_id == j.id)).all()
    sl = ranking_svc.approved_shortlist(db, j.id)
    draft_matches = rubric is not None and rubric_semantics(j.criteria_draft) == rubric_semantics(rubric.criteria)
    return {
        "id": j.id, "slug": j.slug, "title": j.title, "location": j.location, "employment_type": j.employment_type,
        "summary": j.summary, "description": j.description, "status": j.status,
        "criteria_draft": j.criteria_draft, "criteria_draft_digest": _criteria_digest(j.criteria_draft),
        "rubric": {"revision": rubric.revision, "criteria": rubric.criteria, "digest": rubric.digest,
                   "approved_at": rubric.approved_at} if rubric else None,
        "rubric_draft_pending": not draft_matches,
        "weights": {"revision": wrev.revision, "weights": wrev.weights} if wrev else None,
        "shortlist_size": j.shortlist_size, "min_suggest_score": j.min_suggest_score,
        "applications": counts[0], "contact_review": counts[1],
        "assignees": [{"id": a.id, "full_name": a.full_name} for a in assignees],
        "approved_shortlist": {"id": sl.id, "revision": sl.revision, "members": len(sl.members)} if sl else None,
    }


@router.get("/jobs")
def list_jobs(p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    ids = assigned_job_ids(db, p)
    q = select(Job).order_by(Job.created_at.desc())
    if ids is not None:
        q = q.where(Job.id.in_(ids))
    return {"items": [job_staff_out(db, j) for j in db.scalars(q)]}


def _slugify(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:80] or "job"


@router.post("/jobs", status_code=201)
def create_job(body: JobIn, p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    if body.criteria_draft:
        try:
            validate_criteria(body.criteria_draft)
        except ValueError as e:
            raise HTTPException(422, f"Invalid rubric: {e}") from None
    slug = _slugify(body.title)
    if db.scalar(select(Job).where(Job.slug == slug)):
        slug = f"{slug}-{utcnow().strftime('%H%M%S')}"
    j = Job(slug=slug, created_by=p.id, **body.model_dump())
    db.add(j)
    db.flush()
    if p.role == "recruiter":
        db.add(JobAssignment(job_id=j.id, user_id=p.id, created_by=p.id))
    audit(db, p, "job.created", "job", j.id, job_id=j.id)
    db.commit()
    return job_staff_out(db, j)


@router.get("/jobs/{job_id}")
def get_job(job_id: str, p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    return job_staff_out(db, get_job_for_staff(db, p, job_id))


@router.put("/jobs/{job_id}")
def update_job(job_id: str, body: JobIn, p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    j = get_job_for_staff(db, p, job_id, lock=True)
    try:
        crit = [c.model_dump() for c in validate_criteria(body.criteria_draft)] if body.criteria_draft else []
    except ValueError as e:
        raise HTTPException(422, f"Invalid rubric: {e}") from None
    for k, v in body.model_dump(exclude={"criteria_draft"}).items():
        setattr(j, k, v)
    j.criteria_draft = crit
    audit(db, p, "job.updated", "job", j.id, job_id=j.id, digest=_criteria_digest(crit))
    db.commit()
    return job_staff_out(db, j)


@router.patch("/jobs/{job_id}/settings")
def job_settings(job_id: str, body: JobSettingsIn, p: Principal = Depends(require_staff),
                 db: Session = Depends(get_db)):
    j = get_job_for_staff(db, p, job_id, lock=True)
    j.shortlist_size, j.min_suggest_score = body.shortlist_size, body.min_suggest_score
    audit(db, p, "job.settings_changed", "job", j.id, job_id=j.id, details=body.model_dump())
    db.commit()
    return job_staff_out(db, j)


@router.post("/jobs/{job_id}/publish")
def publish(job_id: str, p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    j = get_job_for_staff(db, p, job_id, lock=True)
    if j.current_rubric_revision is None:
        raise HTTPException(409, "Approve the rubric before publishing")
    j.status, j.published_at, j.published_by = "published", utcnow(), p.id
    audit(db, p, "job.published", "job", j.id, job_id=j.id)
    db.commit()
    return job_staff_out(db, j)


@router.post("/jobs/{job_id}/close")
def close(job_id: str, p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    j = get_job_for_staff(db, p, job_id, lock=True)
    j.status = "closed"
    audit(db, p, "job.closed", "job", j.id, job_id=j.id)
    db.commit()
    return job_staff_out(db, j)


class RubricApproveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    criteria_draft_digest: str


@router.post("/jobs/{job_id}/rubric/approve")
def approve_rubric(job_id: str, body: RubricApproveIn, p: Principal = Depends(require_staff),
                   db: Session = Depends(get_db)):
    j = get_job_for_staff(db, p, job_id, lock=True)
    if _criteria_digest(j.criteria_draft) != body.criteria_draft_digest:
        raise HTTPException(409, "Stale rubric: the draft changed since you reviewed it")
    try:
        crit = [c.model_dump() for c in validate_criteria(j.criteria_draft)]
    except ValueError as e:
        raise HTTPException(422, f"Invalid rubric: {e}") from None
    prev = analysis_svc.current_rubric(db, j)
    sem_digest = digest(rubric_semantics(crit))
    weights = normalize_weights({c["id"]: c["weight"] for c in crit})
    if prev is None or prev.digest != sem_digest:
        rev = (prev.revision + 1) if prev else 1
        db.add(RubricRevision(job_id=j.id, revision=rev, criteria=crit, digest=sem_digest, approved_by=p.id))
        j.current_rubric_revision = rev
        audit(db, p, "rubric.approved", "job", j.id, job_id=j.id, revision=rev, digest=sem_digest)
    wprev = ranking_svc.current_weights(db, j)
    if wprev is None or wprev.weights != weights or wprev.rubric_revision != j.current_rubric_revision:
        wrev = (wprev.revision + 1) if wprev else 1
        db.add(WeightsRevision(job_id=j.id, revision=wrev, rubric_revision=j.current_rubric_revision,
                               weights=weights, created_by=p.id))
        j.current_weights_revision = wrev
        audit(db, p, "weights.saved", "job", j.id, job_id=j.id, revision=wrev)
    from ..models import Approval

    db.add(Approval(action="approve_rubric", target_type="job", target_id=j.id,
                    target_revision=j.current_rubric_revision, digest=sem_digest, approver_id=p.id,
                    approver_role=p.role))
    db.commit()
    return job_staff_out(db, j)


class WeightsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    weights: dict[str, float]
    base_revision: int | None = None


def _check_weights(db: Session, j: Job, weights: dict[str, float]) -> dict[str, float]:
    rubric = analysis_svc.current_rubric(db, j)
    if rubric is None:
        raise HTTPException(409, "No approved rubric")
    ids = {c["id"] for c in rubric.criteria}
    if set(weights) != ids:
        raise HTTPException(422, "Weights must cover exactly the approved criteria")
    try:
        return normalize_weights(weights)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None


@router.post("/jobs/{job_id}/weights")
def save_weights(job_id: str, body: WeightsIn, p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    """New weights revision. Zero LLM calls: totals are recomputed from saved criterion ratings."""
    j = get_job_for_staff(db, p, job_id, lock=True)
    if body.base_revision is not None and body.base_revision != j.current_weights_revision:
        raise HTTPException(409, "Stale weights revision")
    w = _check_weights(db, j, body.weights)
    wrev = (j.current_weights_revision or 0) + 1
    db.add(WeightsRevision(job_id=j.id, revision=wrev, rubric_revision=j.current_rubric_revision, weights=w,
                           created_by=p.id))
    j.current_weights_revision = wrev
    audit(db, p, "weights.saved", "job", j.id, job_id=j.id, revision=wrev)
    db.commit()
    return {"revision": wrev, "weights": w, "llm_calls": 0}


# ---- applications --------------------------------------------------------------------


def app_row(a: Application, ev: Evaluation | None) -> dict:
    return {
        "id": a.id, "candidate_name": a.candidate.full_name, "account_email": a.candidate.email,
        "cv_email": a.cv_email, "submitted_at": a.submitted_at, "revision": a.revision, "status": a.status,
        "contact_status": a.contact_status, "contact_reason": a.contact_reason,
        "parse_status": a.document.parse_status, "parse_flags": a.document.parse_flags,
        "pages": a.document.page_count, "filename": a.document.original_filename,
        "evaluation": {"id": ev.id, "state": ev.review_state, "source": ev.source, "flags": ev.review_flags,
                       "rubric_revision": ev.rubric_revision, "model_id": ev.model_id} if ev else None,
    }


@router.get("/jobs/{job_id}/applications")
def list_applications(
    job_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    q: str = Query("", max_length=100),
    parse_status: str | None = Query(None, pattern="^(parsed|needs_review)$"),
    contact_status: str | None = Query(None, pattern="^(ok|review_required)$"),
    evaluation: str | None = Query(None, pattern="^(none|provisional|needs_review|invalid)$"),
    p: Principal = Depends(require_staff),
    db: Session = Depends(get_db),
):
    j = get_job_for_staff(db, p, job_id)
    base = (select(Application).join(User, User.id == Application.candidate_id)
            .join(ResumeDocument, ResumeDocument.id == Application.document_id)
            .where(Application.job_id == j.id, Application.status == "submitted"))
    cur_eval = (select(Evaluation.application_id, Evaluation.review_state)
                .where(Evaluation.job_id == j.id, Evaluation.review_state != "superseded").subquery())
    base = base.outerjoin(cur_eval, cur_eval.c.application_id == Application.id)
    if q:
        like = f"%{q.lower()}%"
        base = base.where(or_(func.lower(User.full_name).like(like), func.lower(User.email).like(like)))
    if parse_status:
        base = base.where(ResumeDocument.parse_status == parse_status)
    if contact_status:
        base = base.where(Application.contact_status == contact_status)
    if evaluation == "none":
        base = base.where(cur_eval.c.review_state.is_(None))
    elif evaluation:
        base = base.where(cur_eval.c.review_state == evaluation)
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    apps = list(db.scalars(base.order_by(Application.submitted_at, Application.id)
                           .offset((page - 1) * page_size).limit(page_size)))
    evs = {e.application_id: e for e in db.scalars(
        select(Evaluation).where(Evaluation.application_id.in_([a.id for a in apps]),
                                 Evaluation.review_state != "superseded"))}
    all_ids_unevaluated = list(db.scalars(
        select(Application.id).outerjoin(cur_eval, cur_eval.c.application_id == Application.id)
        .where(Application.job_id == j.id, Application.status == "submitted", cur_eval.c.review_state.is_(None))))
    return {"items": [app_row(a, evs.get(a.id)) for a in apps], "total": total, "page": page,
            "page_size": page_size, "unevaluated_ids": all_ids_unevaluated}


@router.get("/applications/{application_id}")
def application_detail(application_id: str, p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    a = get_application_for_staff(db, p, application_id)
    evs = list(db.scalars(select(Evaluation).where(Evaluation.application_id == a.id)
                          .order_by(Evaluation.created_at.desc()).limit(10)))
    current = next((e for e in evs if e.review_state != "superseded"), None)
    job = db.get(Job, a.job_id)
    rubric = analysis_svc.current_rubric(db, job)
    wrev = ranking_svc.current_weights(db, job)
    score = None
    if current and rubric and current.result.get("criteria") and current.rubric_revision == rubric.revision:
        score = ranking_svc.score_evaluation(current.result, rubric.criteria, wrev.weights if wrev else {})
    return {
        **app_row(a, current),
        "job": {"id": job.id, "title": job.title},
        "contact": a.document.contact,
        "extracted_pages": a.document.pages,
        "rubric": rubric.criteria if rubric else [],
        "current_evaluation": {
            "id": current.id, "state": current.review_state, "source": current.source, "result": current.result,
            "flags": current.review_flags, "validation_errors": current.validation_errors,
            "model_id": current.model_id, "prompt_version": current.prompt_version,
            "rubric_revision": current.rubric_revision, "created_at": current.created_at,
            "stale": rubric is not None and current.rubric_revision != rubric.revision,
        } if current else None,
        "score": score,
        "history": [{"id": e.id, "state": e.review_state, "source": e.source, "created_at": e.created_at,
                     "rubric_revision": e.rubric_revision, "model_id": e.model_id} for e in evs],
    }


@router.get("/applications/{application_id}/resume")
def application_resume(application_id: str, p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    a = get_application_for_staff(db, p, application_id)
    audit(db, p, "document.downloaded", "application", a.id, job_id=a.job_id)
    db.commit()
    return pdf_response(resume_path(a.document), a.document.original_filename)


# ---- analysis ------------------------------------------------------------------------


class RunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    application_ids: list[str] = Field(max_length=2000)
    rubric_revision: int
    confirm_scope: bool


@router.post("/jobs/{job_id}/analysis-runs", status_code=201)
def start_run(job_id: str, body: RunIn, request: Request, p: Principal = Depends(require_staff),
              db: Session = Depends(get_db)):
    limit(request, "analysis", 20, 3600, key_extra=p.id)
    if not body.confirm_scope:
        raise HTTPException(422, "Explicit confirmation of the analysis scope is required")
    j = get_job_for_staff(db, p, job_id, lock=True)
    run = analysis_svc.authorize_run(db, p, j, body.application_ids, body.rubric_revision)
    db.commit()
    return analysis_svc.run_summary(db, run)


@router.get("/jobs/{job_id}/analysis-runs")
def list_runs(job_id: str, p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    j = get_job_for_staff(db, p, job_id)
    runs = db.scalars(select(AnalysisRun).where(AnalysisRun.job_id == j.id)
                      .order_by(AnalysisRun.authorized_at.desc()).limit(20))
    return {"items": [analysis_svc.run_summary(db, r) for r in runs]}


def _run_for_staff(db: Session, p: Principal, run_id: str) -> AnalysisRun:
    run = db.get(AnalysisRun, run_id)
    if run is None:
        raise HTTPException(404, "Run not found")
    get_job_for_staff(db, p, run.job_id)
    return run


@router.get("/analysis-runs/{run_id}")
def get_run(run_id: str, p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    return analysis_svc.run_summary(db, _run_for_staff(db, p, run_id))


@router.post("/analysis-runs/{run_id}/{action}")
def control_run(run_id: str, action: str, p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    if action not in ("pause", "resume", "cancel"):
        raise HTTPException(404, "Unknown action")
    run = _run_for_staff(db, p, run_id)
    run = db.get(AnalysisRun, run.id, with_for_update=True)
    analysis_svc.set_run_state(db, p, run, action)
    db.commit()
    return analysis_svc.run_summary(db, run)


# ---- ranking & shortlist -------------------------------------------------------------


@router.get("/jobs/{job_id}/ranking")
def ranking(job_id: str, p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    j = get_job_for_staff(db, p, job_id)
    out = ranking_svc.compute_ranking(db, j)
    out["ai_mode"] = llm.current_mode(db)
    return out


class PreviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    weights: dict[str, float]


@router.post("/jobs/{job_id}/ranking/preview")
def ranking_preview(job_id: str, body: PreviewIn, p: Principal = Depends(require_staff),
                    db: Session = Depends(get_db)):
    """What-if reweighting from saved ratings. Makes zero model calls and saves nothing."""
    j = get_job_for_staff(db, p, job_id)
    w = _check_weights(db, j, body.weights)
    return ranking_svc.compute_ranking(db, j, weights_override=w)


def shortlist_out(sl: Shortlist | None) -> dict | None:
    if sl is None:
        return None
    return {"id": sl.id, "revision": sl.revision, "status": sl.status, "members": sl.members,
            "rubric_revision": sl.rubric_revision, "weights_revision": sl.weights_revision, "digest": sl.digest,
            "created_at": sl.created_at, "approved_at": sl.approved_at, "approved_by": sl.approved_by}


@router.get("/jobs/{job_id}/shortlists")
def shortlists(job_id: str, p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    j = get_job_for_staff(db, p, job_id)
    return {"latest": shortlist_out(ranking_svc.latest_shortlist(db, j.id)),
            "approved": shortlist_out(ranking_svc.approved_shortlist(db, j.id))}


class MemberIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    application_id: str
    override_reason: str = Field(default="", max_length=300)


class ShortlistIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    members: list[MemberIn] = Field(max_length=500)


@router.post("/jobs/{job_id}/shortlists", status_code=201)
def save_shortlist(job_id: str, body: ShortlistIn, p: Principal = Depends(require_staff),
                   db: Session = Depends(get_db)):
    j = get_job_for_staff(db, p, job_id, lock=True)
    sl = ranking_svc.save_shortlist_draft(db, p, j, [m.model_dump() for m in body.members])
    db.commit()
    return shortlist_out(sl)


class ApproveDigestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    digest: str = Field(min_length=64, max_length=64)


@router.post("/jobs/{job_id}/shortlists/{shortlist_id}/approve")
def approve_shortlist(job_id: str, shortlist_id: str, body: ApproveDigestIn,
                      p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    j = get_job_for_staff(db, p, job_id, lock=True)
    sl = ranking_svc.approve_shortlist(db, p, j, shortlist_id, body.digest)
    db.commit()
    return shortlist_out(sl)

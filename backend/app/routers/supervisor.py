"""Supervisor administration: staff accounts, roles, job assignments, AI mode, overview, audit."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import Principal, audit, require_supervisor
from ..models import (
    AnalysisRun,
    Application,
    Approval,
    AuditEvent,
    BookingRequest,
    EmailDraft,
    Interview,
    Job,
    JobAssignment,
    User,
    UserSession,
    utcnow,
)
from ..security import digest, hash_password
from ..services import llm
from ..services.ranking import approved_shortlist, latest_shortlist
from ..services.text_tools import is_safe_email

router = APIRouter(prefix="/api/supervisor", tags=["supervisor"])


def staff_out(db: Session, u: User) -> dict:
    jobs = db.execute(select(Job.id, Job.title).join(JobAssignment, JobAssignment.job_id == Job.id)
                      .where(JobAssignment.user_id == u.id)).all()
    return {"id": u.id, "email": u.email, "full_name": u.full_name, "role": u.role, "is_active": u.is_active,
            "created_at": u.created_at, "jobs": [{"id": j.id, "title": j.title} for j in jobs]}


@router.get("/users")
def users(role: str | None = Query(None, pattern="^(candidate|recruiter|supervisor)$"),
          p: Principal = Depends(require_supervisor), db: Session = Depends(get_db)):
    q = select(User).order_by(User.role, User.full_name)
    if role:
        q = q.where(User.role == role)
    return {"items": [staff_out(db, u) for u in db.scalars(q.limit(500))]}


class StaffIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=254)
    full_name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=12, max_length=200)
    role: str = Field(pattern="^(recruiter|supervisor)$")


@router.post("/users", status_code=201)
def create_staff(body: StaffIn, p: Principal = Depends(require_supervisor), db: Session = Depends(get_db)):
    email = body.email.lower()
    if not is_safe_email(email):
        raise HTTPException(422, "Invalid email")
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "Email already in use")
    u = User(email=email, full_name=body.full_name, role=body.role, password_hash=hash_password(body.password),
             created_by=p.id)
    db.add(u)
    db.flush()
    db.add(Approval(action="create_staff_account", target_type="user", target_id=u.id, digest=digest({"email": email, "role": body.role}),
                    approver_id=p.id, approver_role=p.role))
    audit(db, p, "account.staff_created", "user", u.id, details={"role": body.role})
    db.commit()
    return staff_out(db, u)


class UserPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: str | None = Field(default=None, pattern="^(recruiter|supervisor)$")
    is_active: bool | None = None


@router.patch("/users/{user_id}")
def patch_user(user_id: str, body: UserPatch, p: Principal = Depends(require_supervisor),
               db: Session = Depends(get_db)):
    u = db.get(User, user_id, with_for_update=True)
    if u is None:
        raise HTTPException(404, "User not found")
    if u.id == p.id:
        raise HTTPException(409, "You cannot change your own role or status")
    if body.role is not None:
        if u.role == "candidate":
            raise HTTPException(409, "Candidate accounts cannot be promoted to staff; create a staff account instead")
        if body.role != u.role:
            audit(db, p, "account.role_changed", "user", u.id, details={"from": u.role, "to": body.role})
            u.role = body.role
    if body.is_active is not None and body.is_active != u.is_active:
        u.is_active = body.is_active
        if not u.is_active:
            for s in db.scalars(select(UserSession).where(UserSession.user_id == u.id,
                                                          UserSession.revoked_at.is_(None))):
                s.revoked_at = utcnow()
        audit(db, p, "account.activation_changed", "user", u.id, details={"is_active": u.is_active})
    db.commit()
    return staff_out(db, u)


class AssignIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str
    job_id: str


@router.post("/assignments", status_code=201)
def assign(body: AssignIn, p: Principal = Depends(require_supervisor), db: Session = Depends(get_db)):
    u, j = db.get(User, body.user_id), db.get(Job, body.job_id)
    if u is None or j is None or u.role not in ("recruiter", "supervisor"):
        raise HTTPException(422, "Assign an existing staff account to an existing job")
    if not db.scalar(select(JobAssignment).where(JobAssignment.user_id == u.id, JobAssignment.job_id == j.id)):
        db.add(JobAssignment(user_id=u.id, job_id=j.id, created_by=p.id))
        audit(db, p, "assignment.added", "job", j.id, job_id=j.id, details={"user": u.id})
    db.commit()
    return staff_out(db, u)


@router.delete("/assignments")
def unassign(user_id: str, job_id: str, p: Principal = Depends(require_supervisor), db: Session = Depends(get_db)):
    a = db.scalar(select(JobAssignment).where(JobAssignment.user_id == user_id, JobAssignment.job_id == job_id))
    if a:
        db.delete(a)
        audit(db, p, "assignment.removed", "job", job_id, job_id=job_id, details={"user": user_id})
    db.commit()
    return {"ok": True}


class ModeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: str = Field(pattern="^(live|replay)$")


@router.post("/ai-mode")
def ai_mode(body: ModeIn, p: Principal = Depends(require_supervisor), db: Session = Depends(get_db)):
    """Explicit operator action. Runs keep the mode they were authorized with."""
    if body.mode == "live" and not get_settings().live_ai_configured:
        raise HTTPException(409, "Cannot enable live mode: GEMINI_API_KEY is not configured on the server")
    old = llm.current_mode(db)
    llm.set_mode(db, body.mode, p.id)
    audit(db, p, "system.ai_mode_changed", "system", "ai_mode", details={"from": old, "to": body.mode})
    db.commit()
    return {"mode": body.mode}


@router.get("/overview")
def overview(p: Principal = Depends(require_supervisor), db: Session = Depends(get_db)):
    jobs = []
    for j in db.scalars(select(Job).order_by(Job.created_at)):
        apps = db.scalar(select(func.count(Application.id)).where(Application.job_id == j.id,
                                                                  Application.status == "submitted"))
        last_run = db.scalar(select(AnalysisRun).where(AnalysisRun.job_id == j.id)
                             .order_by(AnalysisRun.authorized_at.desc()))
        drafts = dict(db.execute(select(EmailDraft.status, func.count()).where(EmailDraft.job_id == j.id)
                                 .group_by(EmailDraft.status)).all())
        bookings = dict(db.execute(
            select(BookingRequest.status, func.count()).join(Application, Application.id == BookingRequest.application_id)
            .where(Application.job_id == j.id).group_by(BookingRequest.status)).all())
        interviews = db.scalar(select(func.count(Interview.id)).join(Application, Application.id == Interview.application_id)
                               .where(Application.job_id == j.id))
        sl, latest = approved_shortlist(db, j.id), latest_shortlist(db, j.id)
        jobs.append({
            "id": j.id, "title": j.title, "status": j.status, "applications": apps,
            "rubric_revision": j.current_rubric_revision, "weights_revision": j.current_weights_revision,
            "last_run": {"id": last_run.id, "status": last_run.status, "mode": last_run.mode} if last_run else None,
            "shortlist": {"approved_revision": sl.revision if sl else None, "members": len(sl.members) if sl else 0,
                          "latest_status": latest.status if latest else None},
            "emails": drafts, "bookings": bookings, "interviews": interviews,
        })
    counts = dict(db.execute(select(User.role, func.count()).group_by(User.role)).all())
    return {"jobs": jobs, "users": counts, "ai_mode": llm.current_mode(db),
            "live_configured": get_settings().live_ai_configured, "live_calls_today": llm.live_calls_today(db),
            "daily_budget": get_settings().ai_daily_call_budget}


@router.get("/audit")
def audit_log(page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
              action: str | None = Query(None, max_length=80), job_id: str | None = None,
              p: Principal = Depends(require_supervisor), db: Session = Depends(get_db)):
    q = select(AuditEvent)
    if action:
        q = q.where(AuditEvent.action.like(f"{action}%"))
    if job_id:
        q = q.where(AuditEvent.job_id == job_id)
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.scalars(q.order_by(AuditEvent.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    names = {u.id: u.full_name for u in db.scalars(select(User).where(User.id.in_({r.actor_id for r in rows if r.actor_id})))}
    return {"total": total, "page": page, "items": [
        {"id": r.id, "at": r.at, "actor": names.get(r.actor_id, "system"), "actor_role": r.actor_role,
         "action": r.action, "target_type": r.target_type, "target_id": r.target_id, "job_id": r.job_id,
         "revision": r.revision, "digest": r.digest, "outcome": r.outcome, "details": r.details} for r in rows]}


@router.get("/approvals")
def approvals_log(p: Principal = Depends(require_supervisor), db: Session = Depends(get_db)):
    rows = db.scalars(select(Approval).order_by(Approval.created_at.desc()).limit(200)).all()
    names = {u.id: u.full_name for u in db.scalars(select(User).where(User.id.in_({r.approver_id for r in rows})))}
    return {"items": [{"id": a.id, "action": a.action, "target_type": a.target_type, "target_id": a.target_id,
                       "target_revision": a.target_revision, "digest": a.digest, "approver": names.get(a.approver_id),
                       "approver_role": a.approver_role, "created_at": a.created_at} for a in rows]}

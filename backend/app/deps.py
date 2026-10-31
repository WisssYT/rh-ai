from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .models import Application, AuditEvent, Job, JobAssignment, User, UserSession
from .security import SESSION_COOKIE, lookup_session, rate_limiter


@dataclass
class Principal:
    user: User
    session: UserSession

    @property
    def id(self) -> str:
        return self.user.id

    @property
    def role(self) -> str:
        return self.user.role


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def optional_principal(request: Request, db: Session = Depends(get_db)) -> Principal | None:
    s = lookup_session(db, request.cookies.get(SESSION_COOKIE))
    if s is None:
        return None
    return Principal(user=s.user, session=s)


def current_principal(p: Principal | None = Depends(optional_principal)) -> Principal:
    if p is None:
        raise HTTPException(401, "Authentication required")
    return p


def require_role(*roles: str):
    def dep(p: Principal = Depends(current_principal)) -> Principal:
        if p.role not in roles:
            raise HTTPException(403, "This action is not permitted for your role")
        return p

    return dep


require_candidate = require_role("candidate")
require_staff = require_role("recruiter", "supervisor")
require_supervisor = require_role("supervisor")


def limit(request: Request, bucket: str, limit_count: int, window_s: float, key_extra: str = "") -> None:
    key = f"{bucket}:{client_ip(request)}:{key_extra}"
    if not rate_limiter.check(key, limit_count, window_s):
        raise HTTPException(429, "Too many requests - please wait and try again")


# ---- Scope checks (always inside backend queries) ---------------------------------


def assigned_job_ids(db: Session, p: Principal) -> list[str] | None:
    """None means company-wide (supervisor)."""
    if p.role == "supervisor":
        return None
    return list(db.scalars(select(JobAssignment.job_id).where(JobAssignment.user_id == p.id)))


def get_job_for_staff(db: Session, p: Principal, job_id: str, *, lock: bool = False) -> Job:
    q = select(Job).where(Job.id == job_id)
    if p.role != "supervisor":
        q = q.join(JobAssignment, JobAssignment.job_id == Job.id).where(JobAssignment.user_id == p.id)
    if lock:
        q = q.with_for_update(of=Job)
    job = db.scalar(q)
    if job is None:
        # Same response for "missing" and "not assigned" to avoid leaking existence.
        raise HTTPException(404, "Job not found")
    return job


def get_application_for_staff(db: Session, p: Principal, application_id: str) -> Application:
    q = select(Application).where(Application.id == application_id)
    if p.role != "supervisor":
        q = q.join(JobAssignment, JobAssignment.job_id == Application.job_id).where(
            JobAssignment.user_id == p.id
        )
    app = db.scalar(q)
    if app is None:
        raise HTTPException(404, "Application not found")
    return app


def get_application_for_candidate(db: Session, p: Principal, application_id: str) -> Application:
    app = db.scalar(
        select(Application).where(Application.id == application_id, Application.candidate_id == p.id)
    )
    if app is None:
        raise HTTPException(404, "Application not found")
    return app


# ---- Audit ------------------------------------------------------------------------


def audit(
    db: Session,
    actor: Principal | User | None,
    action: str,
    target_type: str,
    target_id: str | None,
    *,
    job_id: str | None = None,
    revision: int | None = None,
    digest: str | None = None,
    outcome: str = "ok",
    correlation_id: str | None = None,
    details: dict | None = None,
) -> None:
    if isinstance(actor, Principal):
        actor_id, role = actor.id, actor.role
    elif isinstance(actor, User):
        actor_id, role = actor.id, actor.role
    else:
        actor_id, role = None, "system"
    db.add(
        AuditEvent(
            actor_id=actor_id,
            actor_role=role,
            action=action,
            target_type=target_type,
            target_id=target_id,
            job_id=job_id,
            revision=revision,
            digest=digest,
            outcome=outcome,
            correlation_id=correlation_id,
            details=details or {},
        )
    )

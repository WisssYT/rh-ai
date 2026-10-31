"""HR: invitation/confirmation drafts and approvals, calendar availability, booking decisions."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import Principal, assigned_job_ids, audit, get_job_for_staff, require_staff
from ..models import (
    Application,
    BookingRequest,
    EmailDraft,
    Interview,
    InterviewSlot,
    Invitation,
    Job,
    JobAssignment,
    Outbox,
    Shortlist,
    User,
    utcnow,
)
from ..services import booking as booking_svc
from ..services import email as email_svc

router = APIRouter(prefix="/api/hr", tags=["hr operations"])


def _scope_filter(db: Session, p: Principal, column):
    ids = assigned_job_ids(db, p)
    return (lambda q: q) if ids is None else (lambda q: q.where(column.in_(ids)))


# ---- email drafts --------------------------------------------------------------------


class PrepareIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    application_ids: list[str] = Field(min_length=1, max_length=200)
    generator: str = Field(pattern="^(ai|template)$")


@router.post("/jobs/{job_id}/invitation-drafts", status_code=201)
def prepare_invitations(job_id: str, body: PrepareIn, p: Principal = Depends(require_staff),
                        db: Session = Depends(get_db)):
    j = get_job_for_staff(db, p, job_id, lock=True)
    out = email_svc.prepare_invitation_drafts(db, p, j, body.application_ids, body.generator)
    db.commit()
    return out


def draft_out(db: Session, d: EmailDraft) -> dict:
    app = db.get(Application, d.application_id)
    job = db.get(Job, d.job_id)
    ob = db.scalar(select(Outbox).where(Outbox.draft_id == d.id).order_by(Outbox.created_at.desc()))
    problem = email_svc.current_context_problem(db, d) if d.status == "draft" else None
    approver = db.get(User, d.approved_by) if d.approved_by else None
    return {
        "id": d.id, "kind": d.kind, "status": d.status, "revision": d.revision, "generator": d.generator,
        "candidate": {"application_id": app.id, "name": app.candidate.full_name,
                      "contact_status": app.contact_status},
        "job": {"id": job.id, "title": job.title},
        "preview": email_svc.compose(d, db),
        "editable_body": d.body,
        "digest": email_svc.draft_digest(d, db),
        "blocking_problem": problem,
        "approved_by": approver.full_name if approver else None, "approved_at": d.approved_at,
        "outbox": {"id": ob.id, "status": ob.status, "transport_result": ob.transport_result,
                   "sent_at": ob.sent_at, "idempotency_key": ob.idempotency_key} if ob else None,
        "created_at": d.created_at, "updated_at": d.updated_at,
    }


def _draft_for_staff(db: Session, p: Principal, draft_id: str) -> EmailDraft:
    d = db.get(EmailDraft, draft_id)
    if d is None:
        raise HTTPException(404, "Draft not found")
    get_job_for_staff(db, p, d.job_id)
    return d


@router.get("/email-drafts")
def list_drafts(job_id: str | None = None, status: str | None = Query(None, max_length=30),
                p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    q = _scope_filter(db, p, EmailDraft.job_id)(select(EmailDraft))
    if job_id:
        q = q.where(EmailDraft.job_id == job_id)
    if status:
        q = q.where(EmailDraft.status == status)
    rows = db.scalars(q.order_by(EmailDraft.created_at.desc()).limit(300))
    return {"items": [draft_out(db, d) for d in rows], "mailpit_url": get_settings().mailpit_ui_url}


@router.get("/email-drafts/{draft_id}")
def get_draft(draft_id: str, p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    return draft_out(db, _draft_for_staff(db, p, draft_id))


class DraftEditIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject: str = Field(max_length=200)
    body: str = Field(max_length=3000)
    revision: int


@router.put("/email-drafts/{draft_id}")
def edit_draft(draft_id: str, body: DraftEditIn, p: Principal = Depends(require_staff),
               db: Session = Depends(get_db)):
    d = _draft_for_staff(db, p, draft_id)
    d = db.get(EmailDraft, d.id, with_for_update=True)
    email_svc.edit_draft(db, p, d, body.subject, body.body, body.revision)
    db.commit()
    return draft_out(db, d)


class ApproveSendIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int
    digest: str = Field(min_length=64, max_length=64)


@router.post("/email-drafts/{draft_id}/approve-send")
def approve_send(draft_id: str, body: ApproveSendIn, p: Principal = Depends(require_staff),
                 db: Session = Depends(get_db)):
    _draft_for_staff(db, p, draft_id)
    out = email_svc.approve_and_send(db, p, draft_id, body.revision, body.digest)
    db.commit()
    return {**out, "draft": draft_out(db, db.get(EmailDraft, draft_id))}


@router.post("/email-drafts/{draft_id}/reject")
def reject(draft_id: str, p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    d = _draft_for_staff(db, p, draft_id)
    d = db.get(EmailDraft, d.id, with_for_update=True)
    email_svc.reject_draft(db, p, d)
    db.commit()
    return draft_out(db, d)


@router.post("/email-drafts/{draft_id}/retry")
def retry(draft_id: str, p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    d = _draft_for_staff(db, p, draft_id)
    email_svc.requeue_failed(db, p, d)
    db.commit()
    return draft_out(db, d)


@router.post("/invitations/{invitation_id}/revoke")
def revoke_invitation(invitation_id: str, p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    inv = db.get(Invitation, invitation_id, with_for_update=True)
    if inv is None:
        raise HTTPException(404, "Invitation not found")
    get_job_for_staff(db, p, inv.job_id)
    if inv.revoked_at is None:
        inv.revoked_at, inv.status = utcnow(), "revoked"
        for d in db.scalars(select(EmailDraft).where(EmailDraft.invitation_id == inv.id, EmailDraft.status == "draft")):
            d.status = "rejected"
        audit(db, p, "invitation.revoked", "invitation", inv.id, job_id=inv.job_id)
    db.commit()
    return {"ok": True}


# ---- calendar ------------------------------------------------------------------------


class SlotItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    location: str = Field(default="", max_length=200)


class SlotsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: str
    interviewer_id: str | None = None
    slots: list[SlotItem] = Field(min_length=1, max_length=50)


def slot_out(db: Session, s: InterviewSlot) -> dict:
    br = db.scalar(select(BookingRequest).where(BookingRequest.slot_id == s.id,
                                                BookingRequest.status.in_(("requested", "confirmed"))))
    iv = db.get(User, s.interviewer_id)
    job = db.get(Job, s.job_id)
    booking = None
    if br is not None:
        app = db.get(Application, br.application_id)
        interview = db.scalar(select(Interview).where(Interview.booking_id == br.id))
        booking = {"id": br.id, "status": br.status, "candidate_name": app.candidate.full_name,
                   "hold_expires_at": br.hold_expires_at, "interview_id": interview.id if interview else None}
    return {"id": s.id, "job": {"id": job.id, "title": job.title}, "interviewer": {"id": iv.id, "name": iv.full_name},
            "starts_at": s.starts_at, "ends_at": s.ends_at, "location": s.location, "status": s.status,
            "booking": booking}


@router.get("/calendar")
def calendar(start: AwareDatetime, end: AwareDatetime, job_id: str | None = None,
             p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    if end <= start or end - start > timedelta(days=62):
        raise HTTPException(422, "Invalid range")
    q = _scope_filter(db, p, InterviewSlot.job_id)(
        select(InterviewSlot).where(InterviewSlot.starts_at < end, InterviewSlot.ends_at > start,
                                    InterviewSlot.status != "cancelled"))
    if job_id:
        q = q.where(InterviewSlot.job_id == job_id)
    return {"timezone": get_settings().company_timezone,
            "items": [slot_out(db, s) for s in db.scalars(q.order_by(InterviewSlot.starts_at))]}


@router.post("/slots", status_code=201)
def create_slots(body: SlotsIn, p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    get_job_for_staff(db, p, body.job_id)
    slots = booking_svc.create_slots(db, p, body.job_id, body.interviewer_id, [s.model_dump() for s in body.slots])
    db.commit()
    return {"items": [slot_out(db, s) for s in slots]}


@router.delete("/slots/{slot_id}")
def delete_slot(slot_id: str, p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    s = db.get(InterviewSlot, slot_id)
    if s is None:
        raise HTTPException(404, "Slot not found")
    get_job_for_staff(db, p, s.job_id)
    if p.role != "supervisor" and s.interviewer_id != p.id:
        raise HTTPException(403, "You can only remove your own availability")
    booking_svc.cancel_slot(db, p, s)
    db.commit()
    return {"ok": True}


@router.get("/interviewers")
def interviewers(job_id: str, p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    get_job_for_staff(db, p, job_id)
    users = db.scalars(select(User).join(JobAssignment, JobAssignment.user_id == User.id)
                       .where(JobAssignment.job_id == job_id, User.is_active.is_(True)))
    items = [{"id": u.id, "name": u.full_name, "role": u.role} for u in users]
    if p.role == "supervisor" and not any(i["id"] == p.id for i in items):
        items.append({"id": p.id, "name": p.user.full_name, "role": p.role})
    return {"items": items}


# ---- bookings ------------------------------------------------------------------------


def booking_out(db: Session, br: BookingRequest) -> dict:
    slot = db.get(InterviewSlot, br.slot_id)
    app = db.get(Application, br.application_id)
    interview = db.scalar(select(Interview).where(Interview.booking_id == br.id))
    conf = None
    if interview:
        d = db.scalar(select(EmailDraft).where(EmailDraft.interview_id == interview.id)
                      .order_by(EmailDraft.created_at.desc()))
        conf = {"id": d.id, "status": d.status} if d else None
    return {"id": br.id, "status": br.status, "candidate_name": app.candidate.full_name, "application_id": app.id,
            "job": {"id": slot.job_id, "title": db.get(Job, slot.job_id).title},
            "slot": {"id": slot.id, "starts_at": slot.starts_at, "ends_at": slot.ends_at, "location": slot.location},
            "hold_expires_at": br.hold_expires_at, "hold_expired": br.hold_expires_at <= utcnow(),
            "created_at": br.created_at, "decided_at": br.decided_at,
            "interview_id": interview.id if interview else None, "confirmation_draft": conf}


@router.get("/booking-requests")
def booking_requests(status: str | None = Query(None, pattern="^(requested|confirmed|declined|expired|cancelled)$"),
                     p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    q = select(BookingRequest).join(InterviewSlot, InterviewSlot.id == BookingRequest.slot_id)
    q = _scope_filter(db, p, InterviewSlot.job_id)(q)
    if status:
        q = q.where(BookingRequest.status == status)
    rows = db.scalars(q.order_by(BookingRequest.created_at.desc()).limit(300))
    return {"items": [booking_out(db, b) for b in rows], "timezone": get_settings().company_timezone}


class DecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str = Field(default="", max_length=300)


@router.post("/booking-requests/{booking_id}/{action}")
def decide_booking(booking_id: str, action: str, body: DecisionIn, p: Principal = Depends(require_staff),
                   db: Session = Depends(get_db)):
    if action not in ("confirm", "decline"):
        raise HTTPException(404, "Unknown action")
    br = db.get(BookingRequest, booking_id)
    if br is None:
        raise HTTPException(404, "Booking not found")
    slot = db.get(InterviewSlot, br.slot_id)
    get_job_for_staff(db, p, slot.job_id)
    try:
        booking_svc.decide(db, p, br, action, body.note)
        db.commit()
    except HTTPException:
        db.commit()  # persist a hold expiry discovered during confirmation
        raise
    return booking_out(db, db.get(BookingRequest, booking_id))


@router.post("/interviews/{interview_id}/confirmation-draft", status_code=201)
def confirmation_draft(interview_id: str, p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    iv = db.get(Interview, interview_id)
    if iv is None:
        raise HTTPException(404, "Interview not found")
    app = db.get(Application, iv.application_id)
    get_job_for_staff(db, p, app.job_id)
    d = email_svc.prepare_confirmation_draft(db, p, iv)
    db.commit()
    return draft_out(db, d)


# ---- approvals inbox -----------------------------------------------------------------


@router.get("/approvals")
def approvals(p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    drafts = db.scalars(_scope_filter(db, p, EmailDraft.job_id)(
        select(EmailDraft).where(EmailDraft.status.in_(("draft", "failed", "delivery_unknown")))))
    bookings = db.scalars(_scope_filter(db, p, InterviewSlot.job_id)(
        select(BookingRequest).join(InterviewSlot, InterviewSlot.id == BookingRequest.slot_id)
        .where(BookingRequest.status == "requested")))
    sls = db.scalars(_scope_filter(db, p, Shortlist.job_id)(select(Shortlist).where(Shortlist.status == "draft")))
    return {
        "email_drafts": [draft_out(db, d) for d in drafts],
        "booking_requests": [booking_out(db, b) for b in bookings],
        "shortlist_drafts": [{"id": s.id, "job_id": s.job_id, "revision": s.revision, "members": len(s.members),
                              "job_title": db.get(Job, s.job_id).title} for s in sls],
        "mailpit_url": get_settings().mailpit_ui_url,
        "timezone": get_settings().company_timezone,
    }



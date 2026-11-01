from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import Principal, audit, get_application_for_candidate, limit, require_candidate
from ..models import Application, BookingRequest, Interview, InterviewSlot, Invitation, Job, RubricRevision, User, UserSession, utcnow
from ..security import hash_password, verify_password
from ..services import booking as booking_svc
from ..services.analysis import ACTIVE_RUN_STATES  # noqa: F401
from ..services.intake import check_contact, resume_path, store_and_parse

router = APIRouter(prefix="/api", tags=["careers & candidate"])


def job_public(j: Job) -> dict:
    return {"id": j.id, "slug": j.slug, "title": j.title, "location": j.location,
            "employment_type": j.employment_type, "summary": j.summary, "description": j.description,
            "published_at": j.published_at}


@router.get("/jobs")
def list_jobs(db: Session = Depends(get_db)):
    jobs = db.scalars(select(Job).where(Job.status == "published").order_by(Job.published_at.desc()))
    return {"items": [job_public(j) for j in jobs]}


@router.get("/jobs/{slug_or_id}")
def get_job(slug_or_id: str, db: Session = Depends(get_db)):
    j = db.scalar(select(Job).where((Job.slug == slug_or_id) | (Job.id == slug_or_id), Job.status == "published"))
    if j is None:
        raise HTTPException(404, "Position not found")
    out = job_public(j)
    rubric = db.scalar(select(RubricRevision).where(RubricRevision.job_id == j.id,
                                                    RubricRevision.revision == j.current_rubric_revision))
    # Transparency for applicants: what the role is assessed on (no weights, no internal anchors).
    out["criteria"] = [{"label": c["label"], "description": c["description"], "required": c.get("required", False)}
                       for c in (rubric.criteria if rubric else [])]
    return out


async def _read_limited(file: UploadFile) -> bytes:
    cap = get_settings().max_upload_bytes
    chunks, size = [], 0
    while True:
        chunk = await file.read(64 * 1024)
        if not chunk:
            break
        size += len(chunk)
        if size > cap:
            raise HTTPException(413, f"File exceeds the {cap // (1024 * 1024)} MB limit")
        chunks.append(chunk)
    return b"".join(chunks)


def application_out(db: Session, a: Application, *, include_text: bool = False) -> dict:
    d = a.document
    out = {
        "id": a.id,
        "job": {"id": a.job.id, "title": a.job.title, "slug": a.job.slug},
        "status": a.status,
        "revision": a.revision,
        "submitted_at": a.submitted_at,
        "contact_status": a.contact_status,
        "contact_reason": a.contact_reason,
        "cv_email": a.cv_email,
        "document": {"filename": d.original_filename, "size_bytes": d.size_bytes, "pages": d.page_count,
                     "parse_status": d.parse_status, "parse_flags": d.parse_flags},
        # Candidates see process stage only - never scores, rankings or AI notes.
        "stage": _stage(db, a),
    }
    if include_text:
        out["extracted_pages"] = d.pages
    return out


def _stage(db: Session, a: Application) -> str:
    inv = db.scalar(select(Invitation).where(Invitation.application_id == a.id, Invitation.status == "sent"))
    if inv:
        iv = db.scalar(select(Interview).where(Interview.application_id == a.id, Interview.status == "confirmed"))
        return "interview_confirmed" if iv else "invited_to_interview"
    if a.status == "withdrawn":
        return "withdrawn"
    return "received"


@router.post("/jobs/{job_id}/applications", status_code=201)
async def apply(
    job_id: str,
    request: Request,
    file: UploadFile = File(...),
    storage_notice_ack: bool = Form(...),
    p: Principal = Depends(require_candidate),
    db: Session = Depends(get_db),
):
    limit(request, "upload", 10, 3600, key_extra=p.id)
    if not storage_notice_ack:
        raise HTTPException(422, "Please confirm the fictional-data and storage notice before submitting")
    job = db.scalar(select(Job).where(Job.id == job_id, Job.status == "published"))
    if job is None:
        raise HTTPException(404, "Position not found or closed")
    if db.scalar(select(Application).where(Application.job_id == job.id, Application.candidate_id == p.id,
                                           Application.status == "submitted")):
        raise HTTPException(409, "You already applied for this position - you can replace your CV instead")
    data = await _read_limited(file)
    doc = store_and_parse(db, p.user, data, file.filename)
    cc = check_contact(doc, p.user.email)
    app = Application(job_id=job.id, candidate_id=p.id, document_id=doc.id, contact_status=cc.status,
                      contact_reason=cc.reason, cv_email=cc.cv_email if cc.status == "ok" else cc.cv_email,
                      storage_notice_ack=True)
    db.add(app)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "You already applied for this position") from None
    audit(db, p, "application.submitted", "application", app.id, job_id=job.id, revision=1,
          details={"parse_status": doc.parse_status, "contact_status": cc.status})
    db.commit()
    return application_out(db, app)


@router.post("/candidate/applications/{application_id}/resume")
async def replace_resume(
    application_id: str,
    request: Request,
    file: UploadFile = File(...),
    storage_notice_ack: bool = Form(...),
    p: Principal = Depends(require_candidate),
    db: Session = Depends(get_db),
):
    """Explicit candidate correction. Material change -> new revision; dependent AI artifacts become stale."""
    limit(request, "upload", 10, 3600, key_extra=p.id)
    if not storage_notice_ack:
        raise HTTPException(422, "Please confirm the storage notice")
    app = get_application_for_candidate(db, p, application_id)
    if app.status != "submitted":
        raise HTTPException(409, "Application is not active")
    data = await _read_limited(file)
    doc = store_and_parse(db, p.user, data, file.filename)
    cc = check_contact(doc, p.user.email)
    app.document_id, app.revision, app.updated_at = doc.id, app.revision + 1, utcnow()
    app.contact_status, app.contact_reason, app.cv_email = cc.status, cc.reason, cc.cv_email
    audit(db, p, "application.resume_replaced", "application", app.id, job_id=app.job_id, revision=app.revision,
          details={"contact_status": cc.status})
    db.commit()
    db.refresh(app)
    return application_out(db, app)


@router.post("/candidate/applications/{application_id}/withdraw")
def withdraw(application_id: str, p: Principal = Depends(require_candidate), db: Session = Depends(get_db)):
    app = get_application_for_candidate(db, p, application_id)
    if app.status != "submitted":
        raise HTTPException(409, "Application is not active")
    app.status = "withdrawn"
    audit(db, p, "application.withdrawn", "application", app.id, job_id=app.job_id)
    db.commit()
    return {"ok": True}


@router.get("/candidate/applications")
def my_applications(p: Principal = Depends(require_candidate), db: Session = Depends(get_db)):
    apps = db.scalars(select(Application).where(Application.candidate_id == p.id)
                      .order_by(Application.submitted_at.desc()))
    return {"items": [application_out(db, a) for a in apps]}


@router.get("/candidate/applications/{application_id}")
def my_application(application_id: str, p: Principal = Depends(require_candidate), db: Session = Depends(get_db)):
    return application_out(db, get_application_for_candidate(db, p, application_id), include_text=True)


def pdf_response(path, filename: str) -> FileResponse:
    return FileResponse(
        path, media_type="application/pdf", filename=filename, content_disposition_type="attachment",
        headers={"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox; default-src 'none'",
                 "Cache-Control": "private, no-store"},
    )


@router.get("/candidate/applications/{application_id}/resume")
def my_resume(application_id: str, p: Principal = Depends(require_candidate), db: Session = Depends(get_db)):
    app = get_application_for_candidate(db, p, application_id)
    return pdf_response(resume_path(app.document), app.document.original_filename)


# ---- invitations & booking ---------------------------------------------------------


def _slot_public(s: InterviewSlot) -> dict:
    # No interviewer identity or other candidates' data.
    return {"id": s.id, "starts_at": s.starts_at, "ends_at": s.ends_at, "location": s.location}


@router.get("/candidate/invitations")
def my_invitations(p: Principal = Depends(require_candidate), db: Session = Depends(get_db)):
    invs = db.scalars(select(Invitation).where(Invitation.candidate_id == p.id, Invitation.status == "sent"))
    items = []
    for inv in invs:
        job = db.get(Job, inv.job_id)
        items.append({"id": inv.id, "job_title": job.title, "expires_at": inv.expires_at,
                      "expired": inv.expires_at <= utcnow(), "revoked": inv.revoked_at is not None})
    return {"items": items}


@router.get("/candidate/invitations/{invitation_id}/slots")
def invitation_slots(invitation_id: str, p: Principal = Depends(require_candidate), db: Session = Depends(get_db)):
    inv = booking_svc.invitation_for_candidate(db, p, invitation_id)
    job = db.get(Job, inv.job_id)
    active = db.scalar(select(BookingRequest).where(BookingRequest.invitation_id == inv.id,
                                                    BookingRequest.status.in_(("requested", "confirmed"))))
    return {
        "invitation": {"id": inv.id, "job_title": job.title, "expires_at": inv.expires_at},
        "timezone": get_settings().company_timezone,
        "active_booking": _booking_out(db, active) if active else None,
        "slots": [_slot_public(s) for s in booking_svc.eligible_slots(db, inv)],
    }


class BookingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slot_id: str = Field(max_length=40)
    idempotency_key: str = Field(min_length=8, max_length=80)


def _booking_out(db: Session, br: BookingRequest) -> dict:
    slot = db.get(InterviewSlot, br.slot_id)
    job = db.get(Job, slot.job_id)
    return {"id": br.id, "status": br.status, "invitation_id": br.invitation_id, "job_title": job.title,
            "slot": _slot_public(slot), "hold_expires_at": br.hold_expires_at, "created_at": br.created_at}


@router.post("/candidate/invitations/{invitation_id}/booking-requests", status_code=201)
def create_booking(invitation_id: str, body: BookingIn, request: Request,
                   p: Principal = Depends(require_candidate), db: Session = Depends(get_db)):
    limit(request, "booking", 30, 600, key_extra=p.id)
    try:
        br, created = booking_svc.request_slot(db, p, invitation_id, body.slot_id, body.idempotency_key)
        db.commit()
    except HTTPException as e:
        db.rollback()
        if e.status_code == 409:
            try:
                inv = booking_svc.invitation_for_candidate(db, p, invitation_id)
                alts = [_slot_public(s) for s in booking_svc.eligible_slots(db, inv)]
            except HTTPException:
                alts = []
            raise HTTPException(409, jsonable_encoder({"message": e.detail, "alternatives": alts})) from None
        raise
    return {"booking": _booking_out(db, br), "created": created}


@router.post("/candidate/bookings/{booking_id}/cancel")
def cancel_booking(booking_id: str, p: Principal = Depends(require_candidate), db: Session = Depends(get_db)):
    br = booking_svc.cancel_request(db, p, booking_id)
    db.commit()
    return {"booking": _booking_out(db, br)}


@router.get("/candidate/bookings")
def my_bookings(p: Principal = Depends(require_candidate), db: Session = Depends(get_db)):
    rows = db.scalars(select(BookingRequest).where(BookingRequest.candidate_id == p.id)
                      .order_by(BookingRequest.created_at.desc()))
    return {"items": [_booking_out(db, b) for b in rows], "timezone": get_settings().company_timezone}


@router.get("/candidate/profile")
def profile(p: Principal = Depends(require_candidate)):
    u: User = p.user
    return {"email": u.email, "full_name": u.full_name, "email_verified": False}


class ProfileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    full_name: str = Field(min_length=2, max_length=120)


@router.patch("/candidate/profile")
def update_profile(body: ProfileIn, p: Principal = Depends(require_candidate), db: Session = Depends(get_db)):
    """Name only. The account email is the identity used for invitations and cannot be changed here."""
    p.user.full_name = body.full_name.strip()
    db.add(p.user)
    audit(db, p, "account.profile_updated", "user", p.id)
    db.commit()
    return {"email": p.user.email, "full_name": p.user.full_name, "email_verified": False}


class PasswordIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=10, max_length=200)


@router.post("/candidate/profile/password")
def change_password(body: PasswordIn, request: Request, p: Principal = Depends(require_candidate),
                    db: Session = Depends(get_db)):
    limit(request, "password", 5, 900, key_extra=p.id)
    if not verify_password(p.user.password_hash, body.current_password):
        audit(db, p, "account.password_change_failed", "user", p.id, outcome="denied")
        db.commit()
        raise HTTPException(400, "Current password is incorrect")
    p.user.password_hash = hash_password(body.new_password)
    db.add(p.user)
    # Sign out every other session; keep the one that made the change.
    for s in db.scalars(select(UserSession).where(UserSession.user_id == p.id, UserSession.revoked_at.is_(None),
                                                  UserSession.id != p.session.id)):
        s.revoked_at = utcnow()
    audit(db, p, "account.password_changed", "user", p.id)
    db.commit()
    return {"ok": True}


# ---- messages to the recruiting team (land in the HR inbox as untrusted content) -------------------


class MessageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject: str = Field(min_length=3, max_length=150)
    body: str = Field(min_length=10, max_length=3000)


def _message_public(m) -> dict:
    # Candidates see their own message and whether it was answered - never triage labels or AI notes.
    return {"id": m.id, "subject": m.subject, "body": m.body, "received_at": m.received_at,
            "answered": m.status == "replied"}


@router.get("/candidate/applications/{application_id}/messages")
def my_messages(application_id: str, p: Principal = Depends(require_candidate), db: Session = Depends(get_db)):
    from ..models import InboxMessage

    a = get_application_for_candidate(db, p, application_id)
    rows = db.scalars(select(InboxMessage).where(InboxMessage.application_id == a.id,
                                                 InboxMessage.from_email == p.user.email)
                      .order_by(InboxMessage.received_at.desc()).limit(50))
    return {"items": [_message_public(m) for m in rows]}


@router.post("/candidate/applications/{application_id}/messages", status_code=201)
def send_message(application_id: str, body: MessageIn, request: Request, p: Principal = Depends(require_candidate),
                 db: Session = Depends(get_db)):
    from ..models import InboxMessage
    from ..services.comms import sanitize_inbound

    limit(request, "candidate_message", 5, 3600, key_extra=p.id)
    a = get_application_for_candidate(db, p, application_id)
    m = InboxMessage(from_email=p.user.email, from_name=p.user.full_name, channel="candidate_portal",
                     subject=sanitize_inbound(body.subject.replace("\n", " "), 150).strip(),
                     body=sanitize_inbound(body.body, 3000), application_id=a.id, job_id=a.job_id)
    db.add(m)
    db.flush()
    audit(db, p, "inbox.message_received", "inbox_message", m.id, job_id=a.job_id, details={"channel": "candidate_portal"})
    db.commit()
    return _message_public(m)


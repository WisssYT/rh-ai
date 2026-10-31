"""Availability, candidate slot requests (temporary holds), HR confirmation, and hold expiry."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import and_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..deps import Principal, audit
from ..models import (
    Application,
    BookingRequest,
    Interview,
    InterviewSlot,
    Invitation,
    JobAssignment,
    User,
    utcnow,
)
from .ranking import approved_shortlist

MIN_MINUTES, MAX_MINUTES = 15, 240


def _lock_interviewer(db: Session, interviewer_id: str) -> None:
    key = int.from_bytes(hashlib.sha256(interviewer_id.encode()).digest()[:8], "big", signed=True)
    db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": key})


def create_slots(db: Session, p: Principal, job_id: str, interviewer_id: str | None, items: list[dict]) -> list[InterviewSlot]:
    interviewer_id = interviewer_id or p.id
    if p.role != "supervisor" and interviewer_id != p.id:
        raise HTTPException(403, "Recruiters can only publish their own availability")
    iv = db.get(User, interviewer_id)
    if iv is None or iv.role not in ("recruiter", "supervisor") or not iv.is_active:
        raise HTTPException(422, "Interviewer must be an active staff account")
    if iv.role == "recruiter" and not db.scalar(
        select(JobAssignment).where(JobAssignment.job_id == job_id, JobAssignment.user_id == iv.id)
    ):
        raise HTTPException(422, "Interviewer is not assigned to this job")
    if not 1 <= len(items) <= 50:
        raise HTTPException(422, "Provide between 1 and 50 slots")
    _lock_interviewer(db, interviewer_id)  # serializes overlap checks for this interviewer
    now = utcnow()
    created = []
    for it in items:
        start, end = it["starts_at"], it["ends_at"]
        if start.tzinfo is None or end.tzinfo is None:
            raise HTTPException(422, "Times must include a timezone offset")
        minutes = (end - start).total_seconds() / 60
        if minutes <= 0:
            raise HTTPException(422, "End time must be after start time")
        if not MIN_MINUTES <= minutes <= MAX_MINUTES:
            raise HTTPException(422, f"Slot duration must be {MIN_MINUTES}-{MAX_MINUTES} minutes")
        if start <= now:
            raise HTTPException(422, "Slots must be in the future")
        clash = db.scalar(
            select(InterviewSlot.id).where(
                InterviewSlot.interviewer_id == interviewer_id,
                InterviewSlot.status != "cancelled",
                InterviewSlot.starts_at < end,
                InterviewSlot.ends_at > start,
            )
        )
        if clash or any(c.starts_at < end and c.ends_at > start for c in created):
            raise HTTPException(409, f"Overlaps existing availability for this interviewer at {start.isoformat()}")
        slot = InterviewSlot(interviewer_id=interviewer_id, job_id=job_id, starts_at=start, ends_at=end,
                             location=(it.get("location") or "Video call (link sent in confirmation)")[:200],
                             created_by=p.id)
        db.add(slot)
        db.flush()
        created.append(slot)
    audit(db, p, "calendar.slots_created", "job", job_id, job_id=job_id, details={"count": len(created)})
    return created


def cancel_slot(db: Session, p: Principal, slot: InterviewSlot) -> None:
    slot = db.get(InterviewSlot, slot.id, with_for_update=True)
    if slot.status != "available":
        raise HTTPException(409, "This slot has an active request or interview; decline/handle it explicitly first")
    slot.status = "cancelled"
    audit(db, p, "calendar.slot_cancelled", "slot", slot.id, job_id=slot.job_id)


# ---- candidate side ------------------------------------------------------------------


def invitation_for_candidate(db: Session, p: Principal, invitation_id: str, *, lock: bool = False) -> Invitation:
    q = select(Invitation).where(Invitation.id == invitation_id, Invitation.candidate_id == p.id,
                                 Invitation.status == "sent")
    if lock:
        q = q.with_for_update()
    inv = db.scalar(q)
    if inv is None:
        raise HTTPException(404, "Invitation not found for this account")
    if inv.revoked_at is not None:
        raise HTTPException(410, "This invitation was withdrawn")
    if inv.expires_at <= utcnow():
        raise HTTPException(410, "This invitation has expired")
    sl = approved_shortlist(db, inv.job_id)
    if sl is None or inv.application_id not in {m["application_id"] for m in sl.members}:
        raise HTTPException(410, "This invitation is no longer active")
    return inv


def eligible_slots(db: Session, inv: Invitation) -> list[InterviewSlot]:
    return list(
        db.scalars(
            select(InterviewSlot).where(
                InterviewSlot.job_id == inv.job_id, InterviewSlot.status == "available",
                InterviewSlot.starts_at > utcnow() + timedelta(hours=1),
            ).order_by(InterviewSlot.starts_at).limit(200)
        )
    )


def request_slot(db: Session, p: Principal, invitation_id: str, slot_id: str, idem_key: str) -> tuple[BookingRequest, bool]:
    if not 8 <= len(idem_key) <= 80:
        raise HTTPException(422, "Invalid idempotency key")
    # Idempotent replay: same candidate + key returns the original request.
    prev = db.scalar(select(BookingRequest).where(BookingRequest.candidate_id == p.id,
                                                  BookingRequest.idempotency_key == idem_key))
    if prev is not None:
        if prev.slot_id != slot_id or prev.invitation_id != invitation_id:
            raise HTTPException(409, "Idempotency key reused for a different request")
        return prev, False
    inv = invitation_for_candidate(db, p, invitation_id, lock=True)
    # Re-check after acquiring the invitation lock (concurrent retries with the same key).
    prev = db.scalar(select(BookingRequest).where(BookingRequest.candidate_id == p.id,
                                                  BookingRequest.idempotency_key == idem_key))
    if prev is not None and prev.slot_id == slot_id:
        return prev, False
    active =db.scalar(select(BookingRequest).where(BookingRequest.invitation_id == inv.id,
                                                    BookingRequest.status.in_(("requested", "confirmed"))))
    if active is not None:
        raise HTTPException(409, "You already have an active request for this invitation - cancel it first")
    slot = db.scalar(select(InterviewSlot).where(InterviewSlot.id == slot_id).with_for_update())
    if slot is None or slot.job_id != inv.job_id:
        raise HTTPException(404, "Slot not found")
    if slot.status != "available" or slot.starts_at <= utcnow() + timedelta(hours=1):
        raise HTTPException(409, "This slot was just taken or is no longer available - pick another time")
    br = BookingRequest(invitation_id=inv.id, slot_id=slot.id, application_id=inv.application_id,
                        candidate_id=p.id, idempotency_key=idem_key,
                        hold_expires_at=utcnow() + timedelta(minutes=get_settings().hold_minutes))
    try:
        with db.begin_nested():
            db.add(br)
            slot.status = "held"
    except IntegrityError:
        raise HTTPException(409, "This slot was just taken - pick another time") from None
    audit(db, p, "booking.requested", "booking", br.id, job_id=inv.job_id,
          details={"slot": slot.id, "hold_expires_at": br.hold_expires_at.isoformat()})
    return br, True


def cancel_request(db: Session, p: Principal, booking_id: str) -> BookingRequest:
    br = db.scalar(select(BookingRequest).where(BookingRequest.id == booking_id,
                                                BookingRequest.candidate_id == p.id).with_for_update())
    if br is None:
        raise HTTPException(404, "Booking not found")
    if br.status != "requested":
        raise HTTPException(409, f"Only pending requests can be cancelled here (state: {br.status})")
    slot = db.get(InterviewSlot, br.slot_id, with_for_update=True)
    br.status = "cancelled"
    if slot.status == "held":
        slot.status = "available"
    audit(db, p, "booking.cancelled_by_candidate", "booking", br.id, job_id=slot.job_id)
    return br


# ---- HR side -------------------------------------------------------------------------


def decide(db: Session, p: Principal, br: BookingRequest, action: str, note: str = "") -> BookingRequest:
    br = db.get(BookingRequest, br.id, with_for_update=True)
    slot = db.get(InterviewSlot, br.slot_id, with_for_update=True)
    if action == "confirm" and br.status == "confirmed":
        return br  # idempotent retry
    if action == "decline" and br.status == "declined":
        return br
    if br.status != "requested":
        raise HTTPException(409, f"Request is {br.status}")
    if action == "confirm":
        if br.hold_expires_at <= utcnow():
            _expire(db, br, slot)
            raise HTTPException(409, "The hold expired before confirmation; the slot was released")
        if slot.starts_at <= utcnow():
            raise HTTPException(409, "The slot is in the past")
        _lock_interviewer(db, slot.interviewer_id)
        overlap = db.scalar(
            select(Interview.id).join(InterviewSlot, InterviewSlot.id == Interview.slot_id).where(
                Interview.interviewer_id == slot.interviewer_id, Interview.status == "confirmed",
                and_(InterviewSlot.starts_at < slot.ends_at, InterviewSlot.ends_at > slot.starts_at))
        )
        if overlap:
            raise HTTPException(409, "Interviewer already has a confirmed interview at that time")
        br.status, br.decided_by, br.decided_at, br.decision_note = "confirmed", p.id, utcnow(), note[:300]
        slot.status = "booked"
        iv = Interview(booking_id=br.id, slot_id=slot.id, application_id=br.application_id,
                       interviewer_id=slot.interviewer_id, confirmed_by=p.id)
        db.add(iv)
        db.flush()
        audit(db, p, "booking.confirmed", "booking", br.id, job_id=slot.job_id, details={"interview": iv.id})
    elif action == "decline":
        br.status, br.decided_by, br.decided_at, br.decision_note = "declined", p.id, utcnow(), note[:300]
        slot.status = "available"
        audit(db, p, "booking.declined", "booking", br.id, job_id=slot.job_id)
    else:
        raise HTTPException(422, "Unknown action")
    return br


def _expire(db: Session, br: BookingRequest, slot: InterviewSlot) -> None:
    br.status = "expired"
    if slot.status == "held":
        slot.status = "available"
    audit(db, None, "booking.hold_expired", "booking", br.id, job_id=slot.job_id, outcome="expired")


def expire_holds(db: Session, now: datetime | None = None) -> int:
    now = now or utcnow()
    rows = db.scalars(
        select(BookingRequest).where(BookingRequest.status == "requested", BookingRequest.hold_expires_at <= now)
        .with_for_update(skip_locked=True)
    ).all()
    for br in rows:
        slot = db.get(InterviewSlot, br.slot_id, with_for_update=True)
        _expire(db, br, slot)
    db.commit()
    return len(rows)


def application_of(db: Session, br: BookingRequest) -> Application:
    return db.get(Application, br.application_id)

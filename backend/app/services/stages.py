"""Pipeline stage of each application, derived only from recorded facts (staff view).

Candidates never see these internal stages - they keep the coarser candidate-facing stage.
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Application,
    BookingRequest,
    EmailDraft,
    Evaluation,
    Interview,
    InterviewScorecard,
    InterviewSlot,
    Invitation,
    Shortlist,
    utcnow,
)

STAGES = ["applied", "evaluated", "shortlisted", "invited", "booking_requested", "interview_scheduled", "interviewed"]
STAGE_LABEL = {
    "applied": "Applied", "evaluated": "Evaluated", "shortlisted": "Shortlisted", "invited": "Invited",
    "booking_requested": "Time requested", "interview_scheduled": "Interview booked", "interviewed": "Interviewed",
    "withdrawn": "Withdrawn", "declined": "Declined",
}


def bulk_stages(db: Session, apps: list[Application], with_base: bool = False):
    """application_id -> furthest stage reached (or withdrawn/declined)."""
    if not apps:
        return ({}, {}) if with_base else {}
    ids = [a.id for a in apps]
    job_ids = {a.job_id for a in apps}
    evaluated = set(db.scalars(select(Evaluation.application_id).where(
        Evaluation.application_id.in_(ids), Evaluation.review_state.in_(("provisional", "needs_review")))))
    shortlisted: set[str] = set()
    for sl in db.scalars(select(Shortlist).where(Shortlist.job_id.in_(job_ids), Shortlist.status == "human_approved")):
        shortlisted |= {m["application_id"] for m in sl.members}
    invited = set(db.scalars(select(Invitation.application_id).where(
        Invitation.application_id.in_(ids), Invitation.status == "sent")))
    requested = set(db.scalars(select(BookingRequest.application_id).where(
        BookingRequest.application_id.in_(ids), BookingRequest.status == "requested")))
    now = utcnow()
    scheduled, interviewed = set(), set()
    rows = db.execute(select(Interview.id, Interview.application_id, InterviewSlot.ends_at)
                      .join(InterviewSlot, InterviewSlot.id == Interview.slot_id)
                      .where(Interview.application_id.in_(ids), Interview.status == "confirmed")).all()
    submitted_cards = set(db.scalars(select(InterviewScorecard.interview_id).where(
        InterviewScorecard.interview_id.in_([r.id for r in rows]), InterviewScorecard.status == "submitted"))) if rows else set()
    for r in rows:
        (interviewed if (r.id in submitted_cards or r.ends_at <= now) else scheduled).add(r.application_id)
    declined = set(db.scalars(select(EmailDraft.application_id).where(
        EmailDraft.application_id.in_(ids), EmailDraft.kind == "decline", EmailDraft.status == "sent")))
    out, base = {}, {}
    for a in apps:
        if a.id in interviewed:
            b = "interviewed"
        elif a.id in scheduled:
            b = "interview_scheduled"
        elif a.id in requested:
            b = "booking_requested"
        elif a.id in invited:
            b = "invited"
        elif a.id in shortlisted:
            b = "shortlisted"
        elif a.id in evaluated:
            b = "evaluated"
        else:
            b = "applied"
        base[a.id] = b
        out[a.id] = "withdrawn" if a.status == "withdrawn" else "declined" if a.id in declined else b
    return (out, base) if with_base else out


def funnel(base: dict[str, str]) -> list[dict]:
    """Cumulative: how many applications reached at least each stage (pass the *base* stages)."""
    reached = defaultdict(int)
    for st in base.values():
        for i in range(STAGES.index(st) + 1):
            reached[STAGES[i]] += 1
    return [{"stage": s, "label": STAGE_LABEL[s], "count": reached[s]} for s in STAGES]

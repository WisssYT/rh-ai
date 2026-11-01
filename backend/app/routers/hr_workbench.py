"""HR workbench: dashboard, review queue, talent pool, inbox brief, follow-ups, templates, interviews, reports.

Same rules as the rest of the HR API: every query is scoped to the caller's assigned jobs inside the backend,
AI output is provisional, and anything that leaves the system is an EmailDraft that a human approves exactly.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
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
    Application,
    BookingRequest,
    EmailDraft,
    EmailTemplate,
    InboxMessage,
    Interview,
    InterviewScorecard,
    InterviewSlot,
    ReviewAck,
    Shortlist,
    User,
    utcnow,
)
from ..services import comms
from ..services import email as email_svc
from ..services import insights
from ..services import interviews as iv_svc
from ..services import templates as tpl
from ..services.analysis import current_rubric
from .hr_ops import draft_out

router = APIRouter(prefix="/api/hr", tags=["hr workbench"])


def _in_scope(ids: list[str] | None, job_id: str | None) -> bool:
    return ids is None or job_id is None or job_id in ids


# ---- dashboard & navigation ---------------------------------------------------------------------


@router.get("/dashboard")
def dashboard(job_id: str | None = None, days: int = Query(30, ge=7, le=90),
              p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    """Aggregates only (zero model calls)."""
    ids = assigned_job_ids(db, p)
    if job_id is not None:
        get_job_for_staff(db, p, job_id)
    return insights.dashboard(db, ids, job_id, days)


def _approvals_pending(db: Session, ids: list[str] | None) -> int:
    def sc(q, col):
        return q if ids is None else q.where(col.in_(ids))

    drafts = db.scalar(sc(select(func.count(EmailDraft.id)).where(EmailDraft.status == "draft"), EmailDraft.job_id)) or 0
    bookings = db.scalar(sc(select(func.count(BookingRequest.id)).join(InterviewSlot, InterviewSlot.id == BookingRequest.slot_id)
                            .where(BookingRequest.status == "requested"), InterviewSlot.job_id)) or 0
    sls = db.scalar(sc(select(func.count(Shortlist.id)).where(Shortlist.status == "draft"), Shortlist.job_id)) or 0
    return drafts + bookings + sls


def _messages_query(ids: list[str] | None):
    q = select(InboxMessage)
    if ids is not None:
        q = q.where((InboxMessage.job_id.in_(ids)) | (InboxMessage.job_id.is_(None)))
    return q


@router.get("/nav-counts")
def nav_counts(p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    ids = assigned_job_ids(db, p)
    review = sum(1 for i in insights.review_items(db, ids) if i["ack"] is None)
    inbox = sum(1 for m in db.scalars(_messages_query(ids).where(InboxMessage.status == "open"))
                if m.needs_human is not False)
    due = sum(1 for f in comms.followups_due(db, ids, 48) if f["due"])
    return {"approvals": _approvals_pending(db, ids), "review": review, "inbox": inbox, "followups": due}


# ---- review queue -------------------------------------------------------------------------------


@router.get("/review-queue")
def review_queue(p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    items = insights.review_items(db, assigned_job_ids(db, p))
    return {"items": items, "open": sum(1 for i in items if i["ack"] is None)}


class AckIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=3, max_length=160)
    note: str = Field(default="", max_length=300)


@router.post("/review-queue/ack")
def ack(body: AckIn, p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    # The key must be an item the server itself lists for this user right now - never an arbitrary string.
    item = next((i for i in insights.review_items(db, assigned_job_ids(db, p)) if i["key"] == body.key), None)
    if item is None:
        raise HTTPException(404, "Review item not found")
    if item["ack"] is None:
        db.add(ReviewAck(item_key=item["key"], kind=item["kind"], target_id=item["target_id"], job_id=item["job_id"],
                         note=body.note.strip(), acked_by=p.id))
        audit(db, p, "review.acknowledged", item["kind"], item["target_id"], job_id=item["job_id"],
              details={"key": item["key"], "note": body.note.strip()[:300]})
        db.commit()
    return {"ok": True}


# ---- talent pool ----------------------------------------------------------------------------------


@router.get("/candidates")
def candidates(q: str = Query("", max_length=100), stage: str | None = Query(None, max_length=30),
               p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    items = insights.candidates(db, assigned_job_ids(db, p), q.strip(), stage)
    return {"items": items[:300], "total": len(items)}


@router.get("/candidates/{user_id}")
def candidate(user_id: str, p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    out = insights.candidate_detail(db, assigned_job_ids(db, p), user_id)
    if out is None:
        raise HTTPException(404, "Candidate not found")
    return out


@router.post("/applications/{application_id}/decline-draft", status_code=201)
def decline_draft(application_id: str, p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    """The human has decided; this only prepares the letter. Sending needs approval of the exact text."""
    a = get_application_for_staff(db, p, application_id)
    d = comms.prepare_decline(db, p, a)
    db.commit()
    return draft_out(db, d)


# ---- inbox brief ------------------------------------------------------------------------------------


def _message_for_staff(db: Session, p: Principal, message_id: str) -> InboxMessage:
    m = db.get(InboxMessage, message_id)
    if m is None or not _in_scope(assigned_job_ids(db, p), m.job_id):
        raise HTTPException(404, "Message not found")
    return m


def message_out(db: Session, m: InboxMessage) -> dict:
    app = db.get(Application, m.application_id) if m.application_id else None
    reply = db.scalar(select(EmailDraft).where(EmailDraft.source_message_id == m.id).order_by(EmailDraft.created_at.desc()))
    return {
        "id": m.id, "received_at": m.received_at, "from_email": m.from_email, "from_name": m.from_name,
        "subject": m.subject, "body": m.body, "channel": m.channel, "status": m.status,
        "category": m.category, "urgency": m.urgency, "needs_human": m.needs_human, "summary": m.summary,
        "flags": m.flags or [], "triage_source": m.triage_source, "triaged_at": m.triaged_at,
        "application": {"id": app.id, "candidate_name": app.candidate.full_name, "candidate_user_id": app.candidate_id,
                        "job_id": app.job_id,
                        "job_title": app.job.title, "contact_status": app.contact_status} if app else None,
        "reply_draft": {"id": reply.id, "status": reply.status, "generator": reply.generator} if reply else None,
    }


@router.get("/inbox")
def inbox(status: str = Query("open", pattern="^(open|replied|archived|all)$"),
          p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    q = _messages_query(assigned_job_ids(db, p))
    if status != "all":
        q = q.where(InboxMessage.status == status)
    msgs = list(db.scalars(q.order_by(InboxMessage.received_at.desc()).limit(300)))
    return {"items": [message_out(db, m) for m in msgs], "untriaged": sum(1 for m in msgs if m.triaged_at is None),
            "timezone": get_settings().company_timezone}


class BriefIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message_ids: list[str] | None = Field(default=None, max_length=30)
    include_triaged: bool = False


@router.post("/inbox/brief")
def prepare_brief(body: BriefIn, request: Request, p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    """Explicit authorization to sort open messages (provisional labels only - nothing is sent or answered)."""
    limit(request, "inbox_brief", 30, 3600, key_extra=p.id)
    q = _messages_query(assigned_job_ids(db, p)).where(InboxMessage.status == "open")
    if body.message_ids:
        q = q.where(InboxMessage.id.in_(body.message_ids))
    if not body.include_triaged:
        q = q.where(InboxMessage.triaged_at.is_(None))
    msgs = list(db.scalars(q.order_by(InboxMessage.received_at.desc()).limit(30)))
    out = comms.triage(db, p, msgs)
    db.commit()
    return out


class ReplyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    generator: str = Field(pattern="^(ai|template)$")


@router.post("/inbox/{message_id}/reply-draft", status_code=201)
def reply_draft(message_id: str, body: ReplyIn, p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    m = _message_for_staff(db, p, message_id)
    if m.application_id:
        get_application_for_staff(db, p, m.application_id)
    d, sources = comms.prepare_reply_draft(db, p, m, body.generator)
    db.commit()
    return {**draft_out(db, d), "sources": sources}


@router.post("/inbox/{message_id}/{action}")
def message_action(message_id: str, action: str, p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    if action not in ("archive", "reopen"):
        raise HTTPException(404, "Unknown action")
    m = _message_for_staff(db, p, message_id)
    m.status = "archived" if action == "archive" else "open"
    m.handled_by, m.handled_at = (p.id, utcnow()) if action == "archive" else (None, None)
    audit(db, p, f"inbox.{action}d", "inbox_message", m.id, job_id=m.job_id)
    db.commit()
    return message_out(db, m)


# ---- follow-ups -------------------------------------------------------------------------------------


@router.get("/followups")
def followups(older_than_hours: int = Query(48, ge=0, le=24 * 30), p: Principal = Depends(require_staff),
              db: Session = Depends(get_db)):
    items = comms.followups_due(db, assigned_job_ids(db, p), older_than_hours)
    ids = [f["pending_draft"]["id"] for f in items if f["pending_draft"]]
    drafts = [draft_out(db, d) for d in db.scalars(select(EmailDraft).where(EmailDraft.id.in_(ids)))] if ids else []
    return {"items": items, "pending_drafts": drafts, "older_than_hours": older_than_hours,
            "timezone": get_settings().company_timezone}


class RemindersIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    invitation_ids: list[str] = Field(min_length=1, max_length=100)


@router.post("/followups/reminders", status_code=201)
def prepare_reminders(body: RemindersIn, p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    out = comms.prepare_reminders(db, p, assigned_job_ids(db, p), body.invitation_ids)
    db.commit()
    return out


class BatchItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    revision: int
    digest: str = Field(min_length=64, max_length=64)


class BatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[BatchItem] = Field(min_length=1, max_length=50)
    confirm_recipients: bool


@router.post("/email-drafts/batch-approve")
def batch_approve(body: BatchIn, p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    """One click for an enumerated list - but still one approval per exact draft revision + digest."""
    if not body.confirm_recipients:
        raise HTTPException(422, "Confirm the listed recipients first")
    ids = assigned_job_ids(db, p)
    results = []
    for it in body.items:
        d = db.get(EmailDraft, it.id)
        if d is None or not _in_scope(ids, d.job_id):
            results.append({"id": it.id, "ok": False, "reason": "not found"})
            continue
        try:
            with db.begin_nested():
                r = email_svc.approve_and_send(db, p, it.id, it.revision, it.digest)
            results.append({"id": it.id, "ok": True, "status": r["status"], "to": d.to_email})
        except HTTPException as e:
            results.append({"id": it.id, "ok": False, "reason": e.detail, "to": d.to_email})
    db.commit()
    return {"results": results, "approved": sum(1 for r in results if r["ok"])}


# ---- templates ----------------------------------------------------------------------------------------


class TemplateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str = Field(max_length=20)
    name: str = Field(min_length=2, max_length=120)
    subject: str = Field(min_length=3, max_length=150)
    body: str = Field(min_length=10, max_length=3000)
    is_default: bool = False


def template_out(db: Session, t: EmailTemplate) -> dict:
    u = db.get(User, t.updated_by or t.created_by)
    return {"id": t.id, "kind": t.kind, "name": t.name, "subject": t.subject, "body": t.body,
            "is_default": t.is_default, "updated_at": t.updated_at, "updated_by": u.full_name if u else None}


SAMPLE = {"first_name": "Amira", "job_title": "Backend Developer (Python)", "company_name": "Nordlicht Robotics (fictional)",
          "interview_instructions": "The first interview takes about 45 minutes.",
          "stage_sentence": "Your application has been received and is being reviewed by the recruiting team."}


@router.get("/templates")
def list_templates(p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    rows = db.scalars(select(EmailTemplate).order_by(EmailTemplate.kind, EmailTemplate.name))
    return {"items": [template_out(db, t) for t in rows], "kinds": list(tpl.KINDS), "placeholders": tpl.PLACEHOLDERS,
            "builtin": tpl.BUILTIN}


def _set_default(db: Session, t: EmailTemplate) -> None:
    for other in db.scalars(select(EmailTemplate).where(EmailTemplate.kind == t.kind, EmailTemplate.id != t.id)):
        other.is_default = False
    t.is_default = True


@router.post("/templates", status_code=201)
def create_template(body: TemplateIn, p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    tpl.validate(body.kind, body.subject, body.body)
    t = EmailTemplate(kind=body.kind, name=body.name.strip(), subject=body.subject.strip(), body=body.body,
                      created_by=p.id, updated_by=p.id)
    db.add(t)
    db.flush()
    if body.is_default:
        _set_default(db, t)
    audit(db, p, "template.created", "email_template", t.id, details={"kind": t.kind, "default": t.is_default})
    db.commit()
    return template_out(db, t)


@router.put("/templates/{template_id}")
def update_template(template_id: str, body: TemplateIn, p: Principal = Depends(require_staff),
                    db: Session = Depends(get_db)):
    t = db.get(EmailTemplate, template_id, with_for_update=True)
    if t is None:
        raise HTTPException(404, "Template not found")
    tpl.validate(body.kind, body.subject, body.body)
    t.kind, t.name, t.subject, t.body = body.kind, body.name.strip(), body.subject.strip(), body.body
    t.updated_by, t.updated_at = p.id, utcnow()
    if body.is_default:
        _set_default(db, t)
    else:
        t.is_default = False
    audit(db, p, "template.updated", "email_template", t.id, details={"kind": t.kind, "default": t.is_default})
    db.commit()
    return template_out(db, t)


@router.delete("/templates/{template_id}")
def delete_template(template_id: str, p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    t = db.get(EmailTemplate, template_id)
    if t is None:
        raise HTTPException(404, "Template not found")
    db.delete(t)
    audit(db, p, "template.deleted", "email_template", template_id, details={"kind": t.kind})
    db.commit()
    return {"ok": True}


class PreviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str = Field(max_length=20)
    subject: str = Field(max_length=150)
    body: str = Field(max_length=3000)


@router.post("/templates/preview")
def preview_template(body: PreviewIn, p: Principal = Depends(require_staff)):
    tpl.validate(body.kind, body.subject, body.body)
    return {"subject": tpl.render(body.subject, SAMPLE), "body": tpl.render(body.body, SAMPLE), "sample": SAMPLE}


# ---- interviews ---------------------------------------------------------------------------------------


def _interview_for_staff(db: Session, p: Principal, interview_id: str) -> Interview:
    iv = db.get(Interview, interview_id)
    if iv is None:
        raise HTTPException(404, "Interview not found")
    get_application_for_staff(db, p, iv.application_id)
    return iv


def interview_row(db: Session, iv: Interview, me: str) -> dict:
    slot = db.get(InterviewSlot, iv.slot_id)
    app = db.get(Application, iv.application_id)
    interviewer = db.get(User, iv.interviewer_id)
    kit = iv_svc.latest_kit(db, iv.id)
    cards = list(db.scalars(select(InterviewScorecard).where(InterviewScorecard.interview_id == iv.id)))
    mine = next((c for c in cards if c.interviewer_id == me), None)
    conf = db.scalar(select(EmailDraft).where(EmailDraft.interview_id == iv.id).order_by(EmailDraft.created_at.desc()))
    return {
        "id": iv.id, "status": iv.status, "starts_at": slot.starts_at, "ends_at": slot.ends_at, "location": slot.location,
        "past": slot.ends_at <= utcnow(),
        "candidate": {"application_id": app.id, "name": app.candidate.full_name, "user_id": app.candidate_id},
        "job": {"id": app.job_id, "title": app.job.title},
        "interviewer": {"id": interviewer.id, "name": interviewer.full_name},
        "kit": {"revision": kit.revision, "source": kit.source, "created_at": kit.created_at} if kit else None,
        "my_scorecard": {"status": mine.status, "recommendation": mine.recommendation} if mine else None,
        "scorecards_submitted": sum(1 for c in cards if c.status == "submitted"),
        "confirmation_email": {"id": conf.id, "status": conf.status} if conf else None,
    }


@router.get("/interviews")
def list_interviews(when: str = Query("upcoming", pattern="^(upcoming|past|all)$"),
                    p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    ids = assigned_job_ids(db, p)
    q = (select(Interview).join(InterviewSlot, InterviewSlot.id == Interview.slot_id)
         .join(Application, Application.id == Interview.application_id))
    if ids is not None:
        q = q.where(Application.job_id.in_(ids))
    now = utcnow()
    if when == "upcoming":
        q = q.where(InterviewSlot.ends_at > now).order_by(InterviewSlot.starts_at)
    elif when == "past":
        q = q.where(InterviewSlot.ends_at <= now).order_by(InterviewSlot.starts_at.desc())
    else:
        q = q.order_by(InterviewSlot.starts_at.desc())
    return {"items": [interview_row(db, iv, p.id) for iv in db.scalars(q.limit(200))],
            "timezone": get_settings().company_timezone}


def kit_out(k) -> dict | None:
    if k is None:
        return None
    return {"id": k.id, "revision": k.revision, "source": k.source, "model_id": k.model_id, "items": k.items,
            "created_at": k.created_at, "evaluation_id": k.evaluation_id}


@router.get("/interviews/{interview_id}")
def get_interview(interview_id: str, p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    iv = _interview_for_staff(db, p, interview_id)
    app = db.get(Application, iv.application_id)
    rubric = current_rubric(db, app.job)
    cards = list(db.scalars(select(InterviewScorecard).where(InterviewScorecard.interview_id == iv.id)))
    names = dict(db.execute(select(User.id, User.full_name).where(User.id.in_([c.interviewer_id for c in cards]))).all()) if cards else {}
    mine = next((c for c in cards if c.interviewer_id == p.id), None)
    ev = iv_svc.current_evaluation(db, app.id)
    return {
        **interview_row(db, iv, p.id),
        "criteria": [{"id": c["id"], "label": c["label"], "required": c.get("required", False), "anchors": c["anchors"]}
                     for c in (rubric.criteria if rubric else [])],
        "kit": kit_out(iv_svc.latest_kit(db, iv.id)),
        "evaluation": {"id": ev.id, "source": ev.source, "state": ev.review_state,
                       "stale": rubric is not None and ev.rubric_revision != rubric.revision} if ev else None,
        "my_scorecard": iv_svc.scorecard_out(mine, names),
        "other_scorecards": [iv_svc.scorecard_out(c, names) for c in cards
                             if c.interviewer_id != p.id and c.status == "submitted"],
    }


class KitIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    generator: str = Field(pattern="^(ai|template)$")


@router.post("/interviews/{interview_id}/kit", status_code=201)
def make_kit(interview_id: str, body: KitIn, request: Request, p: Principal = Depends(require_staff),
             db: Session = Depends(get_db)):
    limit(request, "kit", 30, 3600, key_extra=p.id)
    iv = _interview_for_staff(db, p, interview_id)
    k = iv_svc.generate_kit(db, p, iv, body.generator)
    db.commit()
    return kit_out(k)


@router.put("/interviews/{interview_id}/scorecard")
def save_card(interview_id: str, body: iv_svc.ScorecardIn, p: Principal = Depends(require_staff),
              db: Session = Depends(get_db)):
    iv = _interview_for_staff(db, p, interview_id)
    c = iv_svc.save_scorecard(db, p, iv, body, submit=False)
    db.commit()
    return iv_svc.scorecard_out(c)


@router.post("/interviews/{interview_id}/scorecard/submit")
def submit_card(interview_id: str, body: iv_svc.ScorecardIn, p: Principal = Depends(require_staff),
                db: Session = Depends(get_db)):
    iv = _interview_for_staff(db, p, interview_id)
    c = iv_svc.save_scorecard(db, p, iv, body, submit=True)
    db.commit()
    return iv_svc.scorecard_out(c)


# ---- reports --------------------------------------------------------------------------------------------


@router.get("/jobs/{job_id}/report")
def report(job_id: str, p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    j = get_job_for_staff(db, p, job_id)
    out = insights.shortlist_report(db, j)
    audit(db, p, "report.generated", "job", j.id, job_id=j.id,
          revision=out["shortlist"]["revision"] if out["shortlist"] else None)
    db.commit()
    return out


"""Invitation/confirmation drafts, human approve-and-send, and the durable outbox."""

from __future__ import annotations

import json
import re
import smtplib
from datetime import timedelta
from email.message import EmailMessage
from email.utils import make_msgid

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..deps import Principal, audit
from ..models import (
    AICallLog,
    Application,
    Approval,
    Company,
    EmailDraft,
    Interview,
    InterviewSlot,
    Invitation,
    Job,
    Outbox,
    utcnow,
)
from ..security import digest
from . import llm
from .evaluation import DraftOutput
from .llm.base import DraftRequest, ProviderError, QuotaExceeded
from .ranking import approved_shortlist
from .text_tools import URL_RE, is_safe_email

RESERVED_DOMAINS = (".test", ".example", ".invalid", ".localhost")
RESERVED_EXACT = {"example.com", "example.org", "example.net"}
LOCAL_SMTP_HOSTS = {"localhost", "127.0.0.1", "::1", "mailpit"}

DRAFT_SYSTEM = """You write short, professional interview invitation emails for an HR team.
Write ONLY a subject line and a plain-text body (max 120 words) inviting the candidate to an interview
for the named job. Use only the facts provided in the trusted context. Do not include any links, URLs,
email addresses, phone numbers, dates or times - the system appends the booking link, expiry and contact
details itself. Do not mention scores, rankings, other candidates or AI. Return JSON {"subject","body"}."""


def company(db: Session) -> Company:
    c = db.get(Company, 1)
    if c is None:
        raise HTTPException(500, "Company is not configured - run the seed command")
    return c


def booking_url(invitation_id: str) -> str:
    base = get_settings().public_app_url.rstrip("/")  # trusted configuration only
    return f"{base}/candidate/interviews/{invitation_id}"


def _clean_line(s: str, limit: int) -> str:
    return re.sub(r"[\r\n\t\x00-\x1f]", " ", s).strip()[:limit]


def _strip_untrusted_links(s: str) -> str:
    s = URL_RE.sub("[link removed]", s)
    s = re.sub(r"\S+@\S+\.\S+", "[address removed]", s)
    return s.replace("\x00", "")


def _ts(dt) -> int:
    return int(dt.timestamp() * 1_000_000)


def fmt_local(dt, tz) -> str:
    return dt.astimezone(tz).strftime("%A %d %B %Y, %H:%M")


def compose(draft: EmailDraft, db: Session) -> dict:
    """The exact message that will be sent (preview == payload)."""
    s = get_settings()
    c = company(db)
    footer = ""
    if draft.kind == "invitation" and draft.invitation_id:
        inv = db.get(Invitation, draft.invitation_id)
        footer = (
            f"\n\nChoose an interview time (log in with your candidate account):\n{draft.link_url}\n"
            f"This invitation expires on {fmt_local(inv.expires_at, s.tz)} ({s.company_timezone}).\n"
            f"Questions? Reply to {c.contact_email}.\n\n"
            f"-- {c.name} recruiting team. Fictional hackathon demo message."
        )
    elif draft.kind == "confirmation":
        footer = (f"\n\nQuestions? Reply to {c.contact_email}.\n\n"
                  f"-- {c.name} recruiting team. Fictional hackathon demo message.")
    return {
        "from": s.smtp_from,
        "to": draft.to_email,
        "subject": draft.subject,
        "body": draft.body + footer,
        "link_url": draft.link_url,
    }


def draft_digest(draft: EmailDraft, db: Session) -> str:
    return digest({"id": draft.id, "rev": draft.revision, "ctx": draft.context_digest, "msg": compose(draft, db)})


# ---- dependency (context) validation -------------------------------------------------


def invitation_context_digest(db: Session, app: Application, inv: Invitation) -> str:
    sl = approved_shortlist(db, app.job_id)
    return digest(
        {"shortlist": sl.id if sl else None, "app_rev": app.revision, "email": app.cv_email,
         "contact": app.contact_status, "inv": inv.id, "exp": _ts(inv.expires_at),
         "revoked": inv.revoked_at is not None}
    )


def confirmation_context_digest(db: Session, interview: Interview) -> str:
    slot = db.get(InterviewSlot, interview.slot_id)
    app = db.get(Application, interview.application_id)
    return digest({"interview": interview.id, "status": interview.status, "start": _ts(slot.starts_at),
                   "end": _ts(slot.ends_at), "loc": slot.location, "email": app.cv_email,
                   "contact": app.contact_status})


def current_context_problem(db: Session, draft: EmailDraft) -> str | None:
    app = db.get(Application, draft.application_id)
    if app.contact_status != "ok" or not app.cv_email or app.cv_email != draft.to_email:
        return "Recipient contact data changed or needs review"
    if draft.kind == "invitation":
        inv = db.get(Invitation, draft.invitation_id)
        sl = approved_shortlist(db, app.job_id)
        if sl is None or app.id not in {m["application_id"] for m in sl.members}:
            return "Candidate is no longer on the current approved shortlist"
        if inv.revoked_at is not None or inv.status == "revoked":
            return "Invitation was revoked"
        if inv.expires_at <= utcnow():
            return "Invitation expired"
        if draft.link_url != booking_url(inv.id):
            return "Booking destination does not match configuration"
        if invitation_context_digest(db, app, inv) != draft.context_digest:
            return "Shortlist, contact or invitation details changed since the draft was prepared"
    else:
        iv = db.get(Interview, draft.interview_id)
        if iv is None or iv.status != "confirmed":
            return "Interview is not confirmed"
        if confirmation_context_digest(db, iv) != draft.context_digest:
            return "Booking details changed since the draft was prepared"
    return None


# ---- preparation ---------------------------------------------------------------------


def _first_name(full: str) -> str:
    return (full.split() or ["there"])[0][:40]


def _template_invitation(ctx: dict) -> dict:
    return {
        "subject": f"Interview invitation - {ctx['job_title']}",
        "body": (
            f"Hello {ctx['candidate_first_name']},\n\n"
            f"Thank you for your application for the {ctx['job_title']} position at {ctx['company_name']}. "
            f"We would like to invite you to an interview to talk about your experience and the role.\n\n"
            f"{ctx['interview_instructions']}"
        ).strip(),
    }


def prepare_invitation_drafts(
    db: Session, p: Principal, job: Job, application_ids: list[str], generator: str
) -> dict:
    if generator not in ("ai", "template"):
        raise HTTPException(422, "generator must be 'ai' or 'template'")
    sl = approved_shortlist(db, job.id)
    if sl is None:
        raise HTTPException(409, "Approve a shortlist before preparing invitations")
    members = {m["application_id"] for m in sl.members}
    s = get_settings()
    c = company(db)
    created, skipped = [], []
    mode = llm.current_mode(db)
    for aid in dict.fromkeys(application_ids):
        if aid not in members:
            skipped.append({"application_id": aid, "reason": "not on the approved shortlist"})
            continue
        app = db.scalar(select(Application).where(Application.id == aid, Application.job_id == job.id))
        if app is None:
            skipped.append({"application_id": aid, "reason": "not found"})
            continue
        if app.contact_status != "ok" or not app.cv_email or not is_safe_email(app.cv_email):
            skipped.append({"application_id": aid, "reason": "contact review required: " + app.contact_reason})
            continue
        existing = db.scalar(
            select(EmailDraft).where(EmailDraft.application_id == aid, EmailDraft.kind == "invitation",
                                     EmailDraft.status.in_(("draft", "approved_queued", "sending", "sent")))
        )
        if existing is not None:
            skipped.append({"application_id": aid, "reason": f"draft already exists ({existing.status})"})
            continue
        inv = db.scalar(select(Invitation).where(Invitation.application_id == aid, Invitation.status != "revoked"))
        if inv is None:
            inv = Invitation(application_id=aid, candidate_id=app.candidate_id, job_id=job.id, shortlist_id=sl.id,
                             expires_at=utcnow() + timedelta(days=s.invitation_valid_days), created_by=p.id)
            db.add(inv)
            db.flush()
        # Context for drafting: ONLY this candidate's approved fields + job + HR-approved instructions.
        ctx = {
            "candidate_first_name": _first_name(app.candidate.full_name),
            "job_title": job.title,
            "company_name": c.name,
            "interview_instructions": c.interview_instructions,
        }
        gen_label = "template"
        content = _template_invitation(ctx)
        if generator == "ai":
            try:
                content, gen_label = _ai_draft(db, mode, ctx), f"ai_{mode}"
            except (ProviderError, QuotaExceeded, ValueError) as e:
                skipped.append({"application_id": aid,
                                "reason": f"AI drafting unavailable ({e}); use the template generator explicitly"})
                continue
        d = EmailDraft(
            kind="invitation", job_id=job.id, application_id=aid, invitation_id=inv.id,
            to_email=app.cv_email,  # trusted backend value, never model output
            subject=_clean_line(content["subject"], 150),
            body=_strip_untrusted_links(content["body"])[:3000],
            link_url=booking_url(inv.id),
            context_digest=invitation_context_digest(db, app, inv),
            generator=gen_label, created_by=p.id,
        )
        db.add(d)
        db.flush()
        audit(db, p, "email.draft_prepared", "email_draft", d.id, job_id=job.id, revision=d.revision,
              details={"kind": "invitation", "generator": gen_label})
        created.append(d.id)
    return {"created": created, "skipped": skipped}


def _ai_draft(db: Session, mode: str, ctx: dict) -> dict:
    llm.check_daily_budget(db, mode)
    provider = llm.provider_for_mode(mode)
    user = "TRUSTED CONTEXT (JSON):\n" + json.dumps(ctx)
    req = DraftRequest(system_prompt=DRAFT_SYSTEM, user_prompt=user,
                       response_schema=DraftOutput.model_json_schema(), context=ctx)
    resp = provider.draft_invitation(req)
    db.add(AICallLog(purpose="drafting", mode=mode, model_id=resp.model_id, outcome="ok",
                     latency_ms=resp.latency_ms, prompt_tokens=resp.usage.prompt_tokens,
                     cached_tokens=resp.usage.cached_tokens, output_tokens=resp.usage.output_tokens,
                     thinking_tokens=resp.usage.thinking_tokens, usage_reported=resp.usage.reported))
    out = DraftOutput.model_validate_json(resp.text)  # extra fields (e.g. "to", "bcc") -> rejected
    return out.model_dump()


def prepare_confirmation_draft(db: Session, p: Principal, interview: Interview) -> EmailDraft:
    if interview.status != "confirmed":
        raise HTTPException(409, "Only confirmed interviews get a confirmation email")
    existing = db.scalar(select(EmailDraft).where(EmailDraft.interview_id == interview.id,
                                                  EmailDraft.status.in_(("draft", "approved_queued", "sending", "sent"))))
    if existing:
        return existing
    app = db.get(Application, interview.application_id)
    if app.contact_status != "ok" or not app.cv_email:
        raise HTTPException(409, "Contact review required before emailing this candidate")
    slot = db.get(InterviewSlot, interview.slot_id)
    job = db.get(Job, app.job_id)
    s = get_settings()
    c = company(db)
    body = (
        f"Hello {_first_name(app.candidate.full_name)},\n\n"
        f"Your interview for the {job.title} position is confirmed:\n\n"
        f"  When: {fmt_local(slot.starts_at, s.tz)} - {slot.ends_at.astimezone(s.tz).strftime('%H:%M')} "
        f"({s.company_timezone})\n  Where: {slot.location}\n\n"
        f"{c.interview_instructions}"
    ).strip()
    d = EmailDraft(kind="confirmation", job_id=job.id, application_id=app.id, interview_id=interview.id,
                   to_email=app.cv_email, subject=f"Interview confirmed - {job.title}", body=body,
                   context_digest=confirmation_context_digest(db, interview), generator="template",
                   created_by=p.id)
    db.add(d)
    db.flush()
    audit(db, p, "email.draft_prepared", "email_draft", d.id, job_id=job.id, revision=1,
          details={"kind": "confirmation", "generator": "template"})
    return d


# ---- edit / approve ------------------------------------------------------------------


def edit_draft(db: Session, p: Principal, draft: EmailDraft, subject: str, body: str, revision: int) -> EmailDraft:
    if draft.status != "draft":
        raise HTTPException(409, f"Draft is {draft.status} and can no longer be edited")
    if draft.revision != revision:
        raise HTTPException(409, "Stale draft revision: it changed since you opened it")
    subject = _clean_line(subject, 150)
    if len(subject) < 3 or len(body.strip()) < 10 or len(body) > 3000:
        raise HTTPException(422, "Subject or body has an invalid length")
    draft.subject, draft.body = subject, body.replace("\x00", "")
    draft.revision += 1
    draft.generator = "edited"
    draft.approved_by = draft.approved_at = draft.approved_digest = None  # any approval is invalid now
    draft.updated_at = utcnow()
    audit(db, p, "email.draft_edited", "email_draft", draft.id, job_id=draft.job_id, revision=draft.revision)
    return draft


def reject_draft(db: Session, p: Principal, draft: EmailDraft) -> EmailDraft:
    if draft.status != "draft":
        raise HTTPException(409, f"Draft is {draft.status}")
    draft.status = "rejected"
    audit(db, p, "email.draft_rejected", "email_draft", draft.id, job_id=draft.job_id, revision=draft.revision)
    return draft


def approve_and_send(db: Session, p: Principal, draft_id: str, revision: int, reviewed_digest: str) -> dict:
    draft = db.get(EmailDraft, draft_id, with_for_update=True)  # row lock -> atomic compare-and-approve
    if draft is None:
        raise HTTPException(404, "Draft not found")
    idem = f"draft:{draft.id}:rev:{revision}"
    if draft.status in ("approved_queued", "sending", "sent", "delivery_unknown") and draft.revision == revision:
        ob = db.scalar(select(Outbox).where(Outbox.idempotency_key == idem))
        return {"outbox_id": ob.id if ob else None, "status": draft.status, "duplicate": True}
    if draft.status != "draft":
        raise HTTPException(409, f"Draft is {draft.status}")
    if draft.revision != revision:
        raise HTTPException(409, "Stale draft revision: it was edited after you reviewed it")
    current = draft_digest(draft, db)
    if current != reviewed_digest:
        raise HTTPException(409, "Stale draft: the reviewed content no longer matches")
    problem = current_context_problem(db, draft)
    if problem:
        raise HTTPException(409, problem)
    payload = compose(draft, db)
    if not is_safe_email(payload["to"]) or not is_safe_email(payload["from"]):
        raise HTTPException(422, "Unsafe recipient or sender address")
    ob = Outbox(draft_id=draft.id, draft_revision=draft.revision, idempotency_key=idem, payload=payload,
                payload_digest=digest(payload))
    try:
        with db.begin_nested():
            db.add(ob)
    except IntegrityError:
        ob = db.scalar(select(Outbox).where(Outbox.idempotency_key == idem))
        return {"outbox_id": ob.id, "status": "approved_queued", "duplicate": True}
    draft.status = "approved_queued"
    draft.approved_by, draft.approved_at, draft.approved_digest = p.id, utcnow(), current
    db.add(Approval(action=f"approve_send_{draft.kind}", target_type="email_draft", target_id=draft.id,
                    target_revision=draft.revision, digest=current, approver_id=p.id, approver_role=p.role))
    audit(db, p, "email.approved_and_queued", "email_draft", draft.id, job_id=draft.job_id,
          revision=draft.revision, digest=current, details={"kind": draft.kind, "outbox": ob.id})
    return {"outbox_id": ob.id, "status": "approved_queued", "duplicate": False}


# ---- outbox worker -------------------------------------------------------------------


def delivery_allowed(to: str) -> bool:
    s = get_settings()
    if s.allow_external_email:
        return True
    domain = to.rsplit("@", 1)[-1].lower()
    return (domain.endswith(RESERVED_DOMAINS) or domain in RESERVED_EXACT) and s.smtp_host in LOCAL_SMTP_HOSTS


def recover_outbox(db: Session) -> int:
    """A message stuck in 'sending' after its lease may or may not have been delivered: never resend blindly."""
    rows = db.scalars(select(Outbox).where(Outbox.status == "sending", Outbox.lease_until < utcnow())).all()
    for ob in rows:
        ob.status = "delivery_unknown"
        ob.transport_result = "worker stopped during SMTP transaction; reconcile in Mailpit before any resend"
        d = db.get(EmailDraft, ob.draft_id)
        d.status = "delivery_unknown"
        audit(db, None, "email.delivery_unknown", "outbox", ob.id, job_id=d.job_id, outcome="unknown")
    db.commit()
    return len(rows)


def dispatch_once(db: Session) -> int:
    row = db.execute(
        text("SELECT id FROM outbox WHERE status='queued' ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1")
    ).first()
    if row is None:
        db.rollback()
        return 0
    ob = db.get(Outbox, row.id)
    draft = db.get(EmailDraft, ob.draft_id)
    # Worker executes only the exact approved payload.
    if draft.approved_digest is None or ob.draft_revision != draft.revision or ob.payload_digest != digest(ob.payload):
        ob.status, ob.transport_result = "failed", "approval mismatch - not sent"
        draft.status = "failed"
        audit(db, None, "email.blocked", "outbox", ob.id, job_id=draft.job_id, outcome="blocked")
        db.commit()
        return 1
    if not delivery_allowed(ob.payload["to"]):
        ob.status, ob.transport_result = "failed", "external delivery disabled (ALLOW_EXTERNAL_EMAIL=false)"
        draft.status = "failed"
        audit(db, None, "email.blocked_external", "outbox", ob.id, job_id=draft.job_id, outcome="blocked")
        db.commit()
        return 1
    ob.status, ob.attempts, ob.lease_until = "sending", ob.attempts + 1, utcnow() + timedelta(minutes=2)
    draft.status = "sending"
    db.commit()

    s = get_settings()
    msg = EmailMessage()
    msg["From"] = ob.payload["from"]
    msg["To"] = ob.payload["to"]
    msg["Subject"] = ob.payload["subject"]
    msg["Message-ID"] = make_msgid(idstring=ob.id[:12], domain="talent-detective.test")
    msg["X-Idempotency-Key"] = ob.idempotency_key
    msg.set_content(ob.payload["body"])  # plain-text part only
    try:
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15) as smtp:
            smtp.send_message(msg)
        ob.status, ob.sent_at, ob.message_id = "sent", utcnow(), msg["Message-ID"]
        ob.transport_result = "accepted by local SMTP (Mailpit)"
        draft.status = "sent"
        if draft.kind == "invitation" and draft.invitation_id:
            inv = db.get(Invitation, draft.invitation_id)
            if inv.status == "pending":
                inv.status = "sent"
        audit(db, None, "email.sent", "outbox", ob.id, job_id=draft.job_id, revision=draft.revision,
              digest=ob.payload_digest, details={"kind": draft.kind})
    except (smtplib.SMTPException, OSError) as e:
        ob.status, ob.transport_result = "failed", f"{type(e).__name__}"
        draft.status = "failed"
        audit(db, None, "email.failed", "outbox", ob.id, job_id=draft.job_id, outcome="failed",
              details={"error": type(e).__name__})
    ob.lease_until = None
    db.commit()
    return 1


def requeue_failed(db: Session, p: Principal, draft: EmailDraft) -> None:
    """Retry an approved payload that definitely failed (connection refused etc.) - same approval, same bytes."""
    ob = db.scalar(select(Outbox).where(Outbox.draft_id == draft.id, Outbox.draft_revision == draft.revision))
    if ob is None or ob.status != "failed" or draft.approved_digest is None:
        raise HTTPException(409, "Only failed, previously approved messages can be retried")
    if current_context_problem(db, draft):
        raise HTTPException(409, current_context_problem(db, draft))
    ob.status, draft.status = "queued", "approved_queued"
    audit(db, p, "email.retry_requested", "outbox", ob.id, job_id=draft.job_id, revision=draft.revision)

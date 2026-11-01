"""SQLAlchemy models.

Three kinds of data are kept distinct:
  * raw submissions (Application, ResumeDocument) created by explicit candidate action,
  * provisional AI artifacts (Evaluation, AI-drafted EmailDraft) created only inside an
    explicitly authorized AnalysisRun / draft request,
  * finalized business decisions (approved Shortlist revisions, sent Outbox messages,
    confirmed Interview records) created only by an authorized human action.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

JSONType = JSON().with_variant(JSONB(), "postgresql")


def new_id() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def TS(nullable: bool = False, **kw):
    return mapped_column(DateTime(timezone=True), nullable=nullable, **kw)


class Company(Base):
    __tablename__ = "company"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    name: Mapped[str] = mapped_column(String(200))
    timezone: Mapped[str] = mapped_column(String(64))
    contact_email: Mapped[str] = mapped_column(String(254))
    interview_instructions: Mapped[str] = mapped_column(Text, default="")
    about: Mapped[str] = mapped_column(Text, default="")


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20), index=True)  # candidate | recruiter | supervisor
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_demo_fixture: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = TS(default=utcnow)
    created_by: Mapped[str | None] = mapped_column(String(32), nullable=True)


class UserSession(Base):
    __tablename__ = "user_sessions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = TS(default=utcnow)
    expires_at: Mapped[datetime] = TS()
    revoked_at: Mapped[datetime | None] = TS(nullable=True)
    user: Mapped[User] = relationship()


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    location: Mapped[str] = mapped_column(String(200), default="")
    employment_type: Mapped[str] = mapped_column(String(60), default="Full-time")
    summary: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | published | closed
    # Editable working copy of the rubric; analysis only ever uses an approved RubricRevision.
    criteria_draft: Mapped[list] = mapped_column(JSONType, default=list)
    current_rubric_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_weights_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shortlist_size: Mapped[int] = mapped_column(Integer, default=20)
    min_suggest_score: Mapped[int] = mapped_column(Integer, default=45)
    created_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = TS(default=utcnow)
    published_at: Mapped[datetime | None] = TS(nullable=True)
    published_by: Mapped[str | None] = mapped_column(String(32), nullable=True)


class JobAssignment(Base):
    __tablename__ = "job_assignments"
    __table_args__ = (UniqueConstraint("job_id", "user_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = TS(default=utcnow)
    created_by: Mapped[str | None] = mapped_column(String(32), nullable=True)


class RubricRevision(Base):
    """Immutable, human-approved rubric (criterion meanings + anchors)."""

    __tablename__ = "rubric_revisions"
    __table_args__ = (UniqueConstraint("job_id", "revision"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    criteria: Mapped[list] = mapped_column(JSONType)
    digest: Mapped[str] = mapped_column(String(64))
    approved_by: Mapped[str] = mapped_column(String(32))
    approved_at: Mapped[datetime] = TS(default=utcnow)


class WeightsRevision(Base):
    """Weights only affect deterministic totals, never criterion interpretation."""

    __tablename__ = "weights_revisions"
    __table_args__ = (UniqueConstraint("job_id", "revision"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    rubric_revision: Mapped[int] = mapped_column(Integer)
    weights: Mapped[dict] = mapped_column(JSONType)  # criterion_id -> weight (sums to 100)
    created_by: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = TS(default=utcnow)


class ParseCache(Base):
    """Reusable parsing work keyed by exact file fingerprint + parser version."""

    __tablename__ = "parse_cache"
    __table_args__ = (UniqueConstraint("sha256", "parser_version"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    parser_version: Mapped[str] = mapped_column(String(40))
    result: Mapped[dict] = mapped_column(JSONType)
    created_at: Mapped[datetime] = TS(default=utcnow)


class ResumeDocument(Base):
    __tablename__ = "resume_documents"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    storage_key: Mapped[str] = mapped_column(String(200))
    source_bytes: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True, deferred=True)
    original_filename: Mapped[str] = mapped_column(String(200))  # display only, never a path
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    parser_version: Mapped[str] = mapped_column(String(40))
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    pages: Mapped[list] = mapped_column(JSONType, default=list)  # [{page, segments:[{id,text}]}]
    text_chars: Mapped[int] = mapped_column(Integer, default=0)
    parse_status: Mapped[str] = mapped_column(String(30))  # parsed | needs_review | failed
    parse_flags: Mapped[list] = mapped_column(JSONType, default=list)
    contact: Mapped[dict] = mapped_column(JSONType, default=dict)  # extracted contact fields
    created_at: Mapped[datetime] = TS(default=utcnow)


class Application(Base):
    __tablename__ = "applications"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("resume_documents.id"))
    status: Mapped[str] = mapped_column(String(20), default="submitted")  # submitted | withdrawn
    revision: Mapped[int] = mapped_column(Integer, default=1)
    contact_status: Mapped[str] = mapped_column(String(30))  # ok | review_required
    contact_reason: Mapped[str] = mapped_column(String(300), default="")
    cv_email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    storage_notice_ack: Mapped[bool] = mapped_column(Boolean, default=False)
    submitted_at: Mapped[datetime] = TS(default=utcnow)
    updated_at: Mapped[datetime] = TS(default=utcnow)
    job: Mapped[Job] = relationship()
    candidate: Mapped[User] = relationship()
    document: Mapped[ResumeDocument] = relationship()

    __table_args__ = (
        Index(
            "uq_active_application",
            "job_id",
            "candidate_id",
            unique=True,
            postgresql_where=text("status = 'submitted'"),
        ),
    )


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    rubric_revision: Mapped[int] = mapped_column(Integer)
    rubric_digest: Mapped[str] = mapped_column(String(64))
    application_ids: Mapped[list] = mapped_column(JSONType)
    scope_digest: Mapped[str] = mapped_column(String(64))
    mode: Mapped[str] = mapped_column(String(10))  # live | replay
    provider: Mapped[str] = mapped_column(String(30))
    model_id: Mapped[str] = mapped_column(String(80))
    prompt_version: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(30), default="queued")
    pause_reason: Mapped[str] = mapped_column(String(300), default="")
    authorized_by: Mapped[str] = mapped_column(String(32))
    authorized_role: Mapped[str] = mapped_column(String(20))
    authorized_at: Mapped[datetime] = TS(default=utcnow)
    finished_at: Mapped[datetime | None] = TS(nullable=True)


class AnalysisTask(Base):
    __tablename__ = "analysis_tasks"
    __table_args__ = (UniqueConstraint("run_id", "application_id"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id", ondelete="CASCADE"), index=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_owner: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_until: Mapped[datetime | None] = TS(nullable=True)
    not_before: Mapped[datetime | None] = TS(nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    evaluation_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    result_source: Mapped[str | None] = mapped_column(String(30), nullable=True)  # live | replay | saved_evaluation
    usage: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = TS(default=utcnow)
    updated_at: Mapped[datetime] = TS(default=utcnow)


class AICallLog(Base):
    """One row per provider call attempt (live) or replay generation. Drives budgets + metrics."""

    __tablename__ = "ai_call_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = TS(default=utcnow, index=True)
    purpose: Mapped[str] = mapped_column(String(30))  # screening | drafting | smoke
    mode: Mapped[str] = mapped_column(String(10))
    model_id: Mapped[str] = mapped_column(String(80))
    run_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    task_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    outcome: Mapped[str] = mapped_column(String(30))  # ok | invalid_output | quota | error | timeout
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cached_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    thinking_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    usage_reported: Mapped[bool] = mapped_column(Boolean, default=False)


class Evaluation(Base):
    __tablename__ = "evaluations"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id"))
    dependency_key: Mapped[str] = mapped_column(String(64), index=True)
    rubric_revision: Mapped[int] = mapped_column(Integer)
    document_sha256: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(30))
    model_id: Mapped[str] = mapped_column(String(80))
    prompt_version: Mapped[str] = mapped_column(String(40))
    source: Mapped[str] = mapped_column(String(20))  # live | replay
    review_state: Mapped[str] = mapped_column(String(20))  # provisional | needs_review | invalid | superseded
    result: Mapped[dict] = mapped_column(JSONType)
    review_flags: Mapped[list] = mapped_column(JSONType, default=list)
    validation_errors: Mapped[list] = mapped_column(JSONType, default=list)
    created_at: Mapped[datetime] = TS(default=utcnow)


class Shortlist(Base):
    """Each revision is a snapshot. human_approved revisions are immutable."""

    __tablename__ = "shortlists"
    __table_args__ = (UniqueConstraint("job_id", "revision"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | human_approved | superseded
    members: Mapped[list] = mapped_column(JSONType, default=list)
    rubric_revision: Mapped[int] = mapped_column(Integer)
    weights_revision: Mapped[int] = mapped_column(Integer)
    digest: Mapped[str] = mapped_column(String(64), default="")
    created_by: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = TS(default=utcnow)
    approved_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    approved_at: Mapped[datetime | None] = TS(nullable=True)


class Invitation(Base):
    __tablename__ = "invitations"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), index=True)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    shortlist_id: Mapped[str] = mapped_column(ForeignKey("shortlists.id"))
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | sent | revoked
    expires_at: Mapped[datetime] = TS()
    revoked_at: Mapped[datetime | None] = TS(nullable=True)
    created_by: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = TS(default=utcnow)
    __table_args__ = (
        Index(
            "uq_live_invitation",
            "application_id",
            unique=True,
            postgresql_where=text("status <> 'revoked'"),
        ),
    )


class EmailDraft(Base):
    __tablename__ = "email_drafts"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(20))  # invitation | confirmation | reminder | reply | decline
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), index=True)
    invitation_id: Mapped[str | None] = mapped_column(ForeignKey("invitations.id"), nullable=True)
    interview_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # reply drafts: the inbound message being answered (the recipient never comes from that message)
    source_message_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    to_email: Mapped[str] = mapped_column(String(254))
    subject: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    link_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    context_digest: Mapped[str] = mapped_column(String(64))  # shortlist/contact/booking dependencies
    revision: Mapped[int] = mapped_column(Integer, default=1)
    generator: Mapped[str] = mapped_column(String(30))  # ai_live | ai_replay | template | edited
    status: Mapped[str] = mapped_column(String(30), default="draft")
    approved_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    approved_at: Mapped[datetime | None] = TS(nullable=True)
    approved_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = TS(default=utcnow)
    updated_at: Mapped[datetime] = TS(default=utcnow)


class Outbox(Base):
    __tablename__ = "outbox"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    draft_id: Mapped[str] = mapped_column(ForeignKey("email_drafts.id"), index=True)
    draft_revision: Mapped[int] = mapped_column(Integer)
    idempotency_key: Mapped[str] = mapped_column(String(120), unique=True)
    payload: Mapped[dict] = mapped_column(JSONType)
    payload_digest: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(30), default="queued")  # queued|sending|sent|failed|delivery_unknown
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_until: Mapped[datetime | None] = TS(nullable=True)
    transport_result: Mapped[str] = mapped_column(Text, default="")
    message_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = TS(default=utcnow)
    sent_at: Mapped[datetime | None] = TS(nullable=True)


class Approval(Base):
    """Server-generated record of a material human approval."""

    __tablename__ = "approvals"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    action: Mapped[str] = mapped_column(String(60), index=True)
    target_type: Mapped[str] = mapped_column(String(40))
    target_id: Mapped[str] = mapped_column(String(64), index=True)
    target_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    digest: Mapped[str] = mapped_column(String(64))
    approver_id: Mapped[str] = mapped_column(String(32))
    approver_role: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = TS(default=utcnow)
    valid: Mapped[bool] = mapped_column(Boolean, default=True)


class InterviewSlot(Base):
    __tablename__ = "interview_slots"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    interviewer_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    starts_at: Mapped[datetime] = TS(index=True)
    ends_at: Mapped[datetime] = TS()
    location: Mapped[str] = mapped_column(String(200), default="Video call (link sent in confirmation)")
    status: Mapped[str] = mapped_column(String(20), default="available")  # available | held | booked | cancelled
    created_by: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = TS(default=utcnow)


class BookingRequest(Base):
    __tablename__ = "booking_requests"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    invitation_id: Mapped[str] = mapped_column(ForeignKey("invitations.id"), index=True)
    slot_id: Mapped[str] = mapped_column(ForeignKey("interview_slots.id"), index=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"))
    candidate_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="requested")
    idempotency_key: Mapped[str] = mapped_column(String(80))
    hold_expires_at: Mapped[datetime] = TS()
    created_at: Mapped[datetime] = TS(default=utcnow)
    decided_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    decided_at: Mapped[datetime | None] = TS(nullable=True)
    decision_note: Mapped[str] = mapped_column(String(300), default="")
    __table_args__ = (
        UniqueConstraint("candidate_id", "idempotency_key", name="uq_booking_idem"),
        Index(
            "uq_active_hold_per_slot",
            "slot_id",
            unique=True,
            postgresql_where=text("status IN ('requested','confirmed')"),
        ),
        Index(
            "uq_active_booking_per_invitation",
            "invitation_id",
            unique=True,
            postgresql_where=text("status IN ('requested','confirmed')"),
        ),
    )


class Interview(Base):
    __tablename__ = "interviews"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    booking_id: Mapped[str] = mapped_column(ForeignKey("booking_requests.id"), unique=True)
    slot_id: Mapped[str] = mapped_column(ForeignKey("interview_slots.id"), unique=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), index=True)
    interviewer_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(20), default="confirmed")
    confirmed_by: Mapped[str] = mapped_column(String(32))
    confirmed_at: Mapped[datetime] = TS(default=utcnow)


class SystemSetting(Base):
    __tablename__ = "system_settings"
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[str] = mapped_column(String(300))
    updated_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    updated_at: Mapped[datetime] = TS(default=utcnow)


class AuditEvent(Base):
    """Application audit trail (append-only by convention; NOT cryptographically tamper-proof)."""

    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = TS(default=utcnow, index=True)
    actor_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    actor_role: Mapped[str] = mapped_column(String(20))
    action: Mapped[str] = mapped_column(String(80), index=True)
    target_type: Mapped[str] = mapped_column(String(40))
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    job_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    outcome: Mapped[str] = mapped_column(String(30), default="ok")
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    details: Mapped[dict] = mapped_column(JSONType, default=dict)


# ---- HR workbench: inbox, templates, interview kits, scorecards, review acknowledgements -----------


class InboxMessage(Base):
    """Inbound message to the HR mailbox (fictional). Body is UNTRUSTED content.

    Triage fields are provisional AI output produced only after an explicit "prepare brief" click.
    """

    __tablename__ = "inbox_messages"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    received_at: Mapped[datetime] = TS(default=utcnow, index=True)
    from_email: Mapped[str] = mapped_column(String(254), index=True)
    from_name: Mapped[str] = mapped_column(String(200), default="")
    subject: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    channel: Mapped[str] = mapped_column(String(20), default="email")  # email | candidate_portal
    # deterministic link to an application (sender == candidate account); scopes visibility
    application_id: Mapped[str | None] = mapped_column(ForeignKey("applications.id"), nullable=True, index=True)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id"), nullable=True, index=True)
    category: Mapped[str | None] = mapped_column(String(30), nullable=True)
    urgency: Mapped[str | None] = mapped_column(String(10), nullable=True)  # high | normal | low
    needs_human: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    summary: Mapped[str] = mapped_column(String(400), default="")
    flags: Mapped[list] = mapped_column(JSONType, default=list)
    triage_source: Mapped[str | None] = mapped_column(String(20), nullable=True)  # live | replay
    triage_model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    triaged_at: Mapped[datetime | None] = TS(nullable=True)
    triaged_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | replied | archived
    handled_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    handled_at: Mapped[datetime | None] = TS(nullable=True)


class EmailTemplate(Base):
    """Staff-authored, company-wide message templates with a fixed placeholder whitelist."""

    __tablename__ = "email_templates"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(20), index=True)  # invitation | reminder | reply | decline
    name: Mapped[str] = mapped_column(String(120))
    subject: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = TS(default=utcnow)
    updated_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    updated_at: Mapped[datetime] = TS(default=utcnow)


class InterviewKit(Base):
    """Provisional interview questions aimed at a candidate's unknowns and unverified claims."""

    __tablename__ = "interview_kits"
    __table_args__ = (UniqueConstraint("interview_id", "revision"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    interview_id: Mapped[str] = mapped_column(ForeignKey("interviews.id", ondelete="CASCADE"), index=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), index=True)
    evaluation_id: Mapped[str] = mapped_column(String(32))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    items: Mapped[list] = mapped_column(JSONType, default=list)
    source: Mapped[str] = mapped_column(String(20))  # live | replay | template
    model_id: Mapped[str] = mapped_column(String(80), default="")
    created_by: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = TS(default=utcnow)


class InterviewScorecard(Base):
    """Interviewer's own structured notes. Submitting is an explicit, audited human record."""

    __tablename__ = "interview_scorecards"
    __table_args__ = (UniqueConstraint("interview_id", "interviewer_id"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    interview_id: Mapped[str] = mapped_column(ForeignKey("interviews.id", ondelete="CASCADE"), index=True)
    interviewer_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    ratings: Mapped[dict] = mapped_column(JSONType, default=dict)  # criterion_id -> 0..4 | null
    notes: Mapped[dict] = mapped_column(JSONType, default=dict)  # criterion_id -> text
    summary: Mapped[str] = mapped_column(Text, default="")
    recommendation: Mapped[str] = mapped_column(String(20), default="undecided")
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | submitted
    revision: Mapped[int] = mapped_column(Integer, default=1)
    digest: Mapped[str] = mapped_column(String(64), default="")
    updated_at: Mapped[datetime] = TS(default=utcnow)
    submitted_at: Mapped[datetime | None] = TS(nullable=True)


class ReviewAck(Base):
    """A human acknowledged a review-queue item (it changes no evaluation or decision)."""

    __tablename__ = "review_acks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_key: Mapped[str] = mapped_column(String(160), unique=True)
    kind: Mapped[str] = mapped_column(String(40))
    target_id: Mapped[str] = mapped_column(String(64), index=True)
    job_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    note: Mapped[str] = mapped_column(String(300), default="")
    acked_by: Mapped[str] = mapped_column(String(32))
    acked_at: Mapped[datetime] = TS(default=utcnow)

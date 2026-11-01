"""Company-wide message templates with a fixed placeholder whitelist (no format-string evaluation)."""

from __future__ import annotations

import re

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import EmailTemplate

KINDS = ("invitation", "reminder", "reply", "decline")
PLACEHOLDERS = {
    "first_name": "Candidate first name",
    "job_title": "Job title",
    "company_name": "Company name",
    "interview_instructions": "Interview instructions (company settings)",
    "stage_sentence": "One sentence about the application stage, as the candidate sees it (replies only)",
}
_PH = re.compile(r"\{([a-z_]+)\}")

BUILTIN: dict[str, dict[str, str]] = {
    "invitation": {
        "name": "Interview invitation (built-in)",
        "subject": "Interview invitation - {job_title}",
        "body": "Hello {first_name},\n\nThank you for your application for the {job_title} position at {company_name}. "
                "We would like to invite you to an interview to talk about your experience and the role.\n\n"
                "{interview_instructions}",
    },
    "reminder": {
        "name": "Booking reminder (built-in)",
        "subject": "Reminder: choose your interview time - {job_title}",
        "body": "Hello {first_name},\n\nA friendly reminder that you are invited to an interview for the {job_title} "
                "position at {company_name}, and we have not received your preferred time yet. "
                "You can pick any free slot using the link below.\n\nIf none of the times work for you, just reply "
                "and we will find another option.",
    },
    "reply": {
        "name": "General reply (built-in)",
        "subject": "Re: your message about {job_title}",
        "body": "Hello {first_name},\n\nThank you for your message about the {job_title} position at {company_name}. "
                "{stage_sentence}\n\nIf your question needs a personal answer, a member of the recruiting team "
                "will follow up with you directly.",
    },
    "decline": {
        "name": "Application decline (built-in)",
        "subject": "Your application for {job_title}",
        "body": "Hello {first_name},\n\nThank you for your interest in the {job_title} position at {company_name} "
                "and for the time you invested in your application. After careful review, we have decided not to "
                "move forward with your application for this role.\n\nWe appreciate your interest and wish you "
                "every success in your search.",
    },
}


def validate(kind: str, subject: str, body: str) -> None:
    if kind not in KINDS:
        raise HTTPException(422, f"kind must be one of {', '.join(KINDS)}")
    for field, text in (("subject", subject), ("body", body)):
        unknown = {m for m in _PH.findall(text) if m not in PLACEHOLDERS}
        if unknown:
            raise HTTPException(422, f"Unknown placeholder(s) in {field}: {', '.join(sorted(unknown))}")
        stripped = _PH.sub("", text)
        if "{" in stripped or "}" in stripped:
            raise HTTPException(422, f"Braces in the {field} are only allowed around a known placeholder")
    if "{stage_sentence}" in body + subject and kind != "reply":
        raise HTTPException(422, "{stage_sentence} is only available in reply templates")
    if any(c in subject for c in "\r\n"):
        raise HTTPException(422, "Subject must be a single line")


def render(text: str, values: dict[str, str]) -> str:
    return _PH.sub(lambda m: values.get(m.group(1), ""), text)


def default_template(db: Session, kind: str) -> EmailTemplate | None:
    return db.scalar(select(EmailTemplate).where(EmailTemplate.kind == kind, EmailTemplate.is_default.is_(True))
                     .order_by(EmailTemplate.updated_at.desc()))


def render_default(db: Session, kind: str, values: dict[str, str]) -> dict:
    t = default_template(db, kind)
    src = {"subject": t.subject, "body": t.body} if t else BUILTIN[kind]
    return {"subject": render(src["subject"], values).strip()[:150], "body": render(src["body"], values).strip(),
            "template": t.name if t else BUILTIN[kind]["name"]}

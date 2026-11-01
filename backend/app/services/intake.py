"""Safe PDF intake: signature checks, private storage, isolated parsing, contact checks."""

from __future__ import annotations

import hashlib
import json
import os
import re
import resource
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import ParseCache, ResumeDocument, User, new_id
from .text_tools import extract_contact, is_safe_email, segment_pages

PARSER_VERSION = "pypdf-6/seg-v1"
WORKER = Path(__file__).with_name("pdf_worker.py")


@dataclass
class ContactCheck:
    status: str  # ok | review_required
    reason: str
    cv_email: str | None


def safe_display_name(filename: str | None) -> str:
    base = os.path.basename((filename or "cv.pdf").replace("\\", "/"))
    base = re.sub(r"[^A-Za-z0-9._ -]", "_", base)[:120].strip() or "cv.pdf"
    return base


def validate_pdf_bytes(data: bytes, filename: str | None) -> None:
    s = get_settings()
    if not (filename or "").lower().endswith(".pdf"):
        raise HTTPException(415, "Only .pdf files are accepted")
    if len(data) == 0:
        raise HTTPException(400, "The uploaded file is empty")
    if len(data) > s.max_upload_bytes:
        raise HTTPException(413, f"File exceeds the {s.max_upload_bytes // (1024 * 1024)} MB limit")
    if b"%PDF-" not in data[:1024]:
        raise HTTPException(415, "File content is not a PDF (signature check failed)")
    if b"%%EOF" not in data[-2048:]:
        raise HTTPException(422, "PDF appears truncated or malformed (no end-of-file marker)")


def _limits():  # runs in the child before exec
    resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024, 768 * 1024 * 1024))
    cpu = int(get_settings().pdf_parse_timeout_seconds) + 2
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))


def parse_pdf_isolated(path: Path) -> dict:
    s = get_settings()
    try:
        proc = subprocess.run(
            [sys.executable, "-I", str(WORKER), str(path), str(s.max_pdf_pages), str(s.max_extracted_chars)],
            capture_output=True,
            timeout=s.pdf_parse_timeout_seconds,
            preexec_fn=_limits,
            env={"PATH": "/usr/bin:/bin"},
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "parse_timeout", "pages": [], "page_count": 0, "flags": [], "truncated": False}
    try:
        return json.loads(proc.stdout[: 4 * 1024 * 1024] or b"{}")
    except json.JSONDecodeError:
        return {"ok": False, "error": "parser_crashed", "pages": [], "page_count": 0, "flags": [], "truncated": False}


def store_and_parse(db: Session, owner: User, data: bytes, filename: str | None) -> ResumeDocument:
    validate_pdf_bytes(data, filename)
    s = get_settings()
    sha = hashlib.sha256(data).hexdigest()
    key = f"{new_id()[:2]}/{new_id()}.pdf"  # server-generated; never derived from user input
    dest = s.upload_path / key
    dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)

    cached = db.scalar(
        select(ParseCache).where(ParseCache.sha256 == sha, ParseCache.parser_version == PARSER_VERSION)
    )
    if cached is not None:
        result = cached.result
    else:
        result = parse_pdf_isolated(dest)
        if result.get("ok") or result.get("error") in {"encrypted_pdf_unsupported"}:
            db.add(ParseCache(sha256=sha, parser_version=PARSER_VERSION, result=result))

    if not result.get("ok"):
        err = result.get("error") or "unknown"
        if err.startswith("too_many_pages"):
            dest.unlink(missing_ok=True)
            raise HTTPException(422, f"PDF has too many pages (limit {s.max_pdf_pages})")
        if err == "encrypted_pdf_unsupported":
            dest.unlink(missing_ok=True)
            raise HTTPException(422, "Encrypted/password-protected PDFs are not supported")
        if err.startswith("malformed_pdf") or err in {"parser_crashed", "parser_failure"}:
            dest.unlink(missing_ok=True)
            raise HTTPException(422, "The PDF could not be read safely (malformed or unsupported)")
        # timeout: keep the file but route to manual review
        flags = [err]
        pages: list = []
        status = "needs_review"
    else:
        flags = list(result.get("flags") or [])
        pages = segment_pages(result["pages"])
        chars = sum(len(p["text"]) for p in result["pages"])
        if result.get("truncated"):
            flags.append("text_truncated_incomplete_extraction")
        if chars < 200:
            flags.append("little_or_no_text_possibly_scanned_needs_manual_review")
        status = "needs_review" if flags else "parsed"

    text_chars = sum(len(seg["text"]) for p in pages for seg in p["segments"])
    doc = ResumeDocument(
        owner_id=owner.id,
        storage_key=key,
        source_bytes=data if s.database_file_storage else None,
        original_filename=safe_display_name(filename),
        size_bytes=len(data),
        sha256=sha,
        parser_version=PARSER_VERSION,
        page_count=int(result.get("page_count") or 0),
        pages=pages,
        text_chars=text_chars,
        parse_status=status,
        parse_flags=flags,
        contact=extract_contact(result.get("pages") or []),
    )
    db.add(doc)
    db.flush()
    return doc


def check_contact(doc: ResumeDocument, account_email: str) -> ContactCheck:
    emails = [e for e in (doc.contact or {}).get("emails", [])]
    valid = [e for e in emails if is_safe_email(e)]
    if not emails:
        return ContactCheck("review_required", "No contact email found in the CV", None)
    if len(valid) != len(emails):
        return ContactCheck("review_required", "CV contains an invalid or unsafe email address", None)
    if len(valid) > 1:
        return ContactCheck("review_required", "CV lists multiple email addresses (ambiguous recipient)", None)
    cv_email = valid[0]
    if cv_email != account_email.lower():
        return ContactCheck(
            "review_required", "CV email does not match the applicant's account email", cv_email
        )
    return ContactCheck("ok", "", cv_email)


def resume_path(doc: ResumeDocument) -> Path:
    base = get_settings().upload_path
    p = (base / doc.storage_key).resolve()
    if base not in p.parents:
        raise HTTPException(404, "Document not found")
    if not p.is_file():
        data = doc.source_bytes
        if data is None:
            raise HTTPException(404, "Document file is unavailable")
        if len(data) != doc.size_bytes or hashlib.sha256(data).hexdigest() != doc.sha256:
            raise HTTPException(500, "Stored document failed its integrity check")
        p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temp = p.with_name(f"{p.name}.{new_id()}.tmp")
        try:
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(temp, p)
        finally:
            temp.unlink(missing_ok=True)
    return p

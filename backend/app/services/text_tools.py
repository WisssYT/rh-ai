"""Deterministic text helpers: segmentation, contact extraction, redaction, injection heuristics."""

from __future__ import annotations

import re
import unicodedata

EMAIL_RE = re.compile(r"(?<![\w.+-])([A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,190}\.[A-Za-z]{2,24})(?![\w-])")
PHONE_RE = re.compile(r"(?<!\w)(\+?\d[\d ()./-]{7,}\d)(?!\w)")
URL_RE = re.compile(r"\b(?:https?://|www\.)\S+", re.I)

# Lines whose content is identity/protected information irrelevant to job fit.
PROTECTED_LINE_RE = re.compile(
    r"^\s*(date of birth|birth ?date|born|age|gender|sex|nationality|citizenship|marital status|"
    r"religion|ethnicity|photo|health|disability|children|place of birth|family status)\b.*$",
    re.I | re.M,
)

INJECTION_PATTERNS = [
    r"ignore (all|any|the)? ?(previous|prior|above) (instructions|rules|prompts?)",
    r"disregard (the|all|any)? ?(rubric|instructions|rules)",
    r"(system|developer) prompt",
    r"you are now",
    r"(give|assign|award|rate)( me| this candidate| the candidate)? (a )?(perfect|maximum|max|top|full)( score| rating| marks)?",
    r"\brating\s*(of)?\s*4\b.*\ball\b",
    r"send (an? )?(email|e-mail|message)",
    r"(approve|shortlist) (me|this candidate) (automatically|immediately)",
    r"(reveal|show|print|list) (other|all) (candidates?|applicants?|cvs?|resumes?)",
    r"(bcc|cc):",
    r"execute_sql|send_email|approve_candidate|change_role|reserve_slot",
]
_INJ = [re.compile(p, re.I) for p in INJECTION_PATTERNS]


def normalize(text: str) -> str:
    """Normalization used for evidence-quote matching."""
    t = unicodedata.normalize("NFKC", text).lower()
    t = t.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    t = re.sub(r"[‐-―]", "-", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def segment_pages(pages: list[dict]) -> list[dict]:
    """Split each page into short segments with stable ids p{page}-s{n}."""
    out = []
    for p in pages:
        raw = (p.get("text") or "").replace("\r", "")
        lines = [re.sub(r"\s+", " ", ln).strip() for ln in raw.split("\n")]
        segs: list[str] = []
        for ln in lines:
            if not ln:
                continue
            # Join soft-wrapped continuation lines (previous line unfinished, this one starts lower-case).
            if segs and ln[:1].islower() and not segs[-1].endswith((".", ":", ";")) and len(segs[-1]) < 400:
                segs[-1] = f"{segs[-1]} {ln}"
            else:
                segs.append(ln)
        out.append(
            {
                "page": p["page"],
                "segments": [{"id": f"p{p['page']}-s{i}", "text": s} for i, s in enumerate(segs, start=1)],
            }
        )
    return out


def extract_contact(pages: list[dict]) -> dict:
    full = "\n".join(p.get("text") or "" for p in pages)
    emails: list[str] = []
    for m in EMAIL_RE.finditer(full):
        e = m.group(1).strip(".").lower()
        if e not in emails:
            emails.append(e)
    phones = []
    for m in PHONE_RE.finditer(full):
        digits = re.sub(r"\D", "", m.group(1))
        if 8 <= len(digits) <= 15 and m.group(1) not in phones:
            phones.append(m.group(1).strip())
    return {"emails": emails[:5], "phones": phones[:3]}


def is_safe_email(value: str) -> bool:
    if not value or len(value) > 254 or any(c in value for c in "\r\n\t\0,;<>\"'() "):
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,190}\.[A-Za-z]{2,24}", value))


def detect_injection(text: str) -> list[str]:
    hits = []
    for rx in _INJ:
        m = rx.search(text)
        if m:
            hits.append(m.group(0)[:80])
    return hits


def redact(text: str, names: list[str]) -> str:
    """Best-effort removal of contact details and protected attributes before scoring.

    This does NOT guarantee fairness; it only reduces irrelevant identity signal.
    """
    t = EMAIL_RE.sub("[EMAIL]", text)
    t = URL_RE.sub("[URL]", t)
    t = PHONE_RE.sub(lambda m: "[PHONE]" if len(re.sub(r"\D", "", m.group(1))) >= 8 else m.group(0), t)
    t = PROTECTED_LINE_RE.sub("[REDACTED PERSONAL DETAIL]", t)
    for n in names:
        for part in {n, *n.split()}:
            part = part.strip()
            if len(part) >= 3:
                t = re.sub(rf"\b{re.escape(part)}\b", "[NAME]", t, flags=re.I)
    return t


def redact_pages(segmented: list[dict], names: list[str]) -> list[dict]:
    return [
        {
            "page": p["page"],
            "segments": [{"id": s["id"], "text": redact(s["text"], names)} for s in p["segments"]],
        }
        for p in segmented
    ]

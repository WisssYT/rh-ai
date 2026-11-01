"""Read-only aggregates for the dashboard, review queue, talent pool and shortlist report.

Everything is computed from recorded facts inside the caller's job scope. No model calls happen here.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import (
    AICallLog,
    Application,
    Approval,
    AuditEvent,
    BookingRequest,
    EmailDraft,
    Evaluation,
    InboxMessage,
    Interview,
    InterviewSlot,
    Invitation,
    Job,
    Outbox,
    ResumeDocument,
    ReviewAck,
    Shortlist,
    User,
    utcnow,
)
from . import llm
from .analysis import current_rubric
from .ranking import approved_shortlist, compute_ranking, current_weights, score_evaluation
from .stages import STAGE_LABEL, bulk_stages, funnel

INJECTION = "possible_prompt_injection"


def scoped_jobs(db: Session, job_ids: list[str] | None) -> list[Job]:
    q = select(Job).order_by(Job.created_at)
    if job_ids is not None:
        q = q.where(Job.id.in_(job_ids))
    return list(db.scalars(q))


def _apps(db: Session, jobs: list[Job]) -> list[Application]:
    if not jobs:
        return []
    return list(db.scalars(select(Application).where(Application.job_id.in_([j.id for j in jobs]))))


def _pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    v = sorted(values)
    k = max(0, min(len(v) - 1, round(q * (len(v) - 1))))
    return round(v[k], 1)


def _hours(a: datetime | None, b: datetime | None) -> float | None:
    if a is None or b is None:
        return None
    return max(0.0, (b - a).total_seconds() / 3600)


# ---- dashboard ----------------------------------------------------------------------------


def dashboard(db: Session, job_ids: list[str] | None, focus_job_id: str | None, days: int) -> dict:
    s = get_settings()
    tz = s.tz
    now = utcnow()
    jobs = scoped_jobs(db, job_ids)
    by_job = {j.id: j for j in jobs}
    apps = _apps(db, jobs)
    active = [a for a in apps if a.status == "submitted"]
    stages, base = bulk_stages(db, apps, with_base=True)
    active_base = {a.id: base[a.id] for a in active}
    fun = funnel(active_base)
    stage_counts = Counter(stages.values())

    # applications over time (company-local dates)
    start_day = (now.astimezone(tz) - timedelta(days=days - 1)).date()
    day_list = [start_day + timedelta(days=i) for i in range(days)]
    per_job: dict[str, Counter] = defaultdict(Counter)
    for a in apps:
        d = a.submitted_at.astimezone(tz).date()
        if d >= start_day:
            per_job[a.job_id][d] += 1
    timeline = {
        "days": [d.isoformat() for d in day_list],
        "series": [{"job_id": j.id, "title": j.title, "values": [per_job[j.id][d] for d in day_list],
                    "total": sum(per_job[j.id].values())} for j in jobs],
        "annotations": [{"date": j.published_at.astimezone(tz).date().isoformat(), "label": f"{j.title} published"}
                        for j in jobs if j.published_at and j.published_at.astimezone(tz).date() >= start_day],
    }

    # focus job for score spread / coverage
    evaluated_per_job = Counter(a.job_id for a in active if base[a.id] != "applied")
    focus = by_job.get(focus_job_id) if focus_job_id else None
    if focus is None and jobs:
        focus = max(jobs, key=lambda j: (evaluated_per_job[j.id], j.created_at))
    spread = coverage = None
    if focus is not None:
        rk = compute_ranking(db, focus)
        scored = [r for r in rk["rows"] if r["lower"] is not None]
        spread = {
            "job": {"id": focus.id, "title": focus.title},
            "cutoff": rk["cutoff"], "min_suggest_score": focus.min_suggest_score,
            "unscored": len(rk["rows"]) - len(scored),
            "points": [{"application_id": r["application_id"], "name": r["candidate_name"], "lower": r["lower"],
                        "upper": r["upper"], "coverage": r["coverage"], "proposed": r["proposed"],
                        "position": r["position"], "near_tie": r["near_tie"],
                        "flagged": INJECTION in (r["review_flags"] or []), "source": r["evaluation_source"]}
                       for r in scored],
        }
        top = scored[:20]
        coverage = {
            "job": {"id": focus.id, "title": focus.title},
            "criteria": rk["criteria"],
            "rows": [{"application_id": r["application_id"], "name": r["candidate_name"], "lower": r["lower"],
                      "ratings": {pc["criterion_id"]: pc["rating"] for pc in r["per_criterion"]}} for r in top],
            "total_scored": len(scored),
        }

    sec = security_counts(db, jobs, apps)

    # AI usage: company-wide (no candidate data), last 14 days
    ai_days = [(now.astimezone(tz) - timedelta(days=13 - i)).date() for i in range(14)]
    ai_start = datetime.combine(ai_days[0], datetime.min.time(), tzinfo=tz)
    calls = db.execute(select(AICallLog.at, AICallLog.mode, AICallLog.purpose, AICallLog.outcome,
                              AICallLog.prompt_tokens, AICallLog.cached_tokens, AICallLog.output_tokens,
                              AICallLog.usage_reported).where(AICallLog.at >= ai_start)).all()
    per_day = defaultdict(Counter)
    purposes, outcomes = Counter(), Counter()
    tok = {"prompt": 0, "cached": 0, "output": 0, "reported_calls": 0}
    for c in calls:
        per_day[c.at.astimezone(tz).date()][c.mode] += 1
        purposes[c.purpose] += 1
        outcomes[c.outcome] += 1
        if c.usage_reported:
            tok["reported_calls"] += 1
            tok["prompt"] += c.prompt_tokens or 0
            tok["cached"] += c.cached_tokens or 0
            tok["output"] += c.output_tokens or 0
    ai = {
        "mode": llm.current_mode(db), "live_calls_today": llm.live_calls_today(db),
        "daily_budget": s.ai_daily_call_budget,
        "days": [d.isoformat() for d in ai_days],
        "live": [per_day[d]["live"] for d in ai_days], "replay": [per_day[d]["replay"] for d in ai_days],
        "purposes": dict(purposes), "outcomes": dict(outcomes), "tokens": tok,
        "cached_share": round(tok["cached"] * 100 / tok["prompt"], 1) if tok["prompt"] else None,
    }

    # human decision speed
    jids = [j.id for j in jobs]
    drafts = list(db.scalars(select(EmailDraft).where(EmailDraft.job_id.in_(jids), EmailDraft.approved_at.is_not(None)))) if jids else []
    email_h = [h for d in drafts if (h := _hours(d.created_at, d.approved_at)) is not None]
    sls = list(db.scalars(select(Shortlist).where(Shortlist.job_id.in_(jids), Shortlist.approved_at.is_not(None)))) if jids else []
    sl_h = [h for sl in sls if (h := _hours(sl.created_at, sl.approved_at)) is not None]
    outbox = Counter(db.scalars(select(Outbox.status).join(EmailDraft, EmailDraft.id == Outbox.draft_id)
                                .where(EmailDraft.job_id.in_(jids)))) if jids else Counter()
    pending_drafts = db.scalar(select(func.count(EmailDraft.id)).where(EmailDraft.job_id.in_(jids),
                                                                      EmailDraft.status == "draft")) if jids else 0
    decisions = {
        "email_approval_hours": {"median": _pct(email_h, 0.5), "p90": _pct(email_h, 0.9), "n": len(email_h)},
        "shortlist_approval_hours": {"median": _pct(sl_h, 0.5), "p90": _pct(sl_h, 0.9), "n": len(sl_h)},
        "outbox": dict(outbox), "pending_drafts": pending_drafts or 0,
        "approvals_recorded": db.scalar(select(func.count(Approval.id))) or 0,
    }

    # calendar load: next 14 days
    cal_days = [(now.astimezone(tz) + timedelta(days=i)).date() for i in range(14)]
    cal_start = datetime.combine(cal_days[0], datetime.min.time(), tzinfo=tz)
    slots = db.execute(select(InterviewSlot.starts_at, InterviewSlot.status).where(
        InterviewSlot.job_id.in_(jids), InterviewSlot.starts_at >= cal_start,
        InterviewSlot.starts_at < cal_start + timedelta(days=14), InterviewSlot.status != "cancelled")).all() if jids else []
    load = defaultdict(Counter)
    for sl in slots:
        load[sl.starts_at.astimezone(tz).date()][sl.status] += 1
    invs = list(db.scalars(select(Invitation).where(Invitation.job_id.in_(jids), Invitation.status == "sent"))) if jids else []
    t2b = []
    for inv in invs:
        br = db.scalar(select(BookingRequest).where(BookingRequest.invitation_id == inv.id)
                       .order_by(BookingRequest.created_at))
        sent = db.scalar(select(Outbox.sent_at).join(EmailDraft, EmailDraft.id == Outbox.draft_id).where(
            EmailDraft.invitation_id == inv.id, EmailDraft.kind == "invitation", Outbox.status == "sent"))
        if br and (h := _hours(sent or inv.created_at, br.created_at)) is not None:
            t2b.append(h)
    calendar = {
        "days": [d.isoformat() for d in cal_days],
        "available": [load[d]["available"] for d in cal_days], "held": [load[d]["held"] for d in cal_days],
        "booked": [load[d]["booked"] for d in cal_days],
        "invite_to_request_hours": {"median": _pct(t2b, 0.5), "n": len(t2b)},
    }

    kpis = {
        "applications": len(active), "withdrawn": stage_counts["withdrawn"], "declined": stage_counts["declined"],
        "evaluated": fun[1]["count"], "shortlisted": fun[2]["count"], "invited": fun[3]["count"],
        "booked": fun[5]["count"], "interviewed": fun[6]["count"],
        "open_jobs": sum(1 for j in jobs if j.status == "published"),
        "evaluation_sources": dict(Counter(db.scalars(select(Evaluation.source).where(
            Evaluation.job_id.in_(jids), Evaluation.review_state != "superseded")))) if jids else {},
    }
    return {"generated_at": now, "timezone": s.company_timezone, "days": days,
            "jobs": [{"id": j.id, "title": j.title, "status": j.status} for j in jobs],
            "kpis": kpis, "funnel": fun, "timeline": timeline, "score_spread": spread, "coverage": coverage,
            "security": sec, "ai": ai, "decisions": decisions, "calendar": calendar, "llm_calls": 0}


def security_counts(db: Session, jobs: list[Job], apps: list[Application]) -> dict:
    jids = [j.id for j in jobs]
    if not jids:
        return {k: 0 for k in ("injection_flags", "suspicious_messages", "invalid_outputs", "quote_check_rejections",
                               "contact_mismatch", "manual_review_documents", "emails_blocked", "schema_rejections")}
    evs = list(db.scalars(select(Evaluation).where(Evaluation.job_id.in_(jids), Evaluation.review_state != "superseded")))
    active = [a for a in apps if a.status == "submitted"]
    docs = {d.id: d for d in db.scalars(select(ResumeDocument).where(
        ResumeDocument.id.in_([a.document_id for a in active])))} if active else {}
    return {
        "injection_flags": sum(1 for e in evs if INJECTION in (e.review_flags or [])),
        "suspicious_messages": sum(1 for m in db.scalars(select(InboxMessage).where(
            (InboxMessage.job_id.in_(jids)) | (InboxMessage.job_id.is_(None)))) if INJECTION in (m.flags or [])),
        "invalid_outputs": sum(1 for e in evs if e.review_state == "invalid"),
        "quote_check_rejections": sum(1 for e in evs if e.validation_errors),
        "contact_mismatch": sum(1 for a in active if a.contact_status != "ok"),
        "manual_review_documents": sum(1 for a in active if docs.get(a.document_id) and docs[a.document_id].parse_status != "parsed"),
        "emails_blocked": db.scalar(select(func.count(AuditEvent.id)).where(
            AuditEvent.action.in_(("email.blocked", "email.blocked_external")), AuditEvent.job_id.in_(jids))) or 0,
        "schema_rejections": db.scalar(select(func.count(AICallLog.id)).where(AICallLog.outcome == "invalid_output")) or 0,
    }


# ---- review queue -----------------------------------------------------------------------------


def review_items(db: Session, job_ids: list[str] | None) -> list[dict]:
    jobs = scoped_jobs(db, job_ids)
    titles = {j.id: j.title for j in jobs}
    jids = list(titles)
    items: list[dict] = []
    if not jids:
        return items

    def add(kind, severity, key, target_id, job_id, title, detail, link, at, application_id=None, candidate=None):
        items.append({"key": key, "kind": kind, "severity": severity, "target_id": target_id, "job_id": job_id,
                      "job_title": titles.get(job_id) if job_id else None, "title": title, "detail": detail,
                      "link": link, "at": at, "application_id": application_id, "candidate_name": candidate})

    apps = {a.id: a for a in db.scalars(select(Application).where(Application.job_id.in_(jids),
                                                                  Application.status == "submitted"))}
    for e in db.scalars(select(Evaluation).where(Evaluation.job_id.in_(jids), Evaluation.review_state != "superseded")):
        a = apps.get(e.application_id)
        if a is None:
            continue
        link = f"/hr/jobs/{a.job_id}/applications?evidence={a.id}"
        if INJECTION in (e.review_flags or []):
            add("injection", "high", f"injection:{e.id}", e.id, a.job_id, "Instruction-like text in CV",
                "The CV contains text that tries to instruct the assistant. It was treated as data; check the "
                "original document before relying on any rating.", link, e.created_at, a.id, a.candidate.full_name)
        if e.review_state == "invalid":
            add("invalid_output", "high", f"invalid:{e.id}", e.id, a.job_id, "AI output rejected",
                "; ".join(str(x) for x in (e.validation_errors or [])[:2]) or "Output failed validation and was not used.",
                link, e.created_at, a.id, a.candidate.full_name)
        elif e.review_state == "needs_review":
            flags = [f for f in (e.review_flags or []) if f != INJECTION]
            add("needs_review", "medium", f"needs_review:{e.id}", e.id, a.job_id, "Evaluation needs a human look",
                ", ".join(f.split(":")[0].replace("_", " ") for f in flags[:3]) or "Flagged during validation.",
                link, e.created_at, a.id, a.candidate.full_name)
    for a in apps.values():
        link = f"/hr/jobs/{a.job_id}/applications?evidence={a.id}"
        if a.document.parse_status != "parsed":
            add("manual_document", "medium", f"document:{a.id}:{a.revision}", a.id, a.job_id,
                "Document could not be read fully", "Little or no text was extracted (e.g. a scanned PDF). Read the "
                "original - this is not a low score.", link, a.updated_at, a.id, a.candidate.full_name)
        if a.contact_status != "ok":
            add("contact", "medium", f"contact:{a.id}:{a.revision}", a.id, a.job_id, "Contact details need review",
                a.contact_reason or "CV email does not match the account.", link, a.updated_at, a.id,
                a.candidate.full_name)
    for m in db.scalars(select(InboxMessage).where((InboxMessage.job_id.in_(jids)) | (InboxMessage.job_id.is_(None)))):
        if INJECTION in (m.flags or []) and m.status == "open":
            add("suspicious_message", "high", f"message:{m.id}", m.id, m.job_id, "Suspicious inbound message",
                f"“{m.subject[:80]}” from {m.from_email} contains instruction-like content. AI replies are blocked.",
                f"/hr/inbox?message={m.id}", m.received_at)
    for d in db.scalars(select(EmailDraft).where(EmailDraft.job_id.in_(jids),
                                                 EmailDraft.status.in_(("failed", "delivery_unknown")))):
        a = db.get(Application, d.application_id)
        add("email_problem", "high", f"email:{d.id}:{d.revision}:{d.status}", d.id, d.job_id,
            "Email delivery problem" if d.status == "failed" else "Delivery unknown",
            f"{d.kind.capitalize()} to {d.to_email}: " + ("check Mailpit before any resend." if d.status == "delivery_unknown"
                                                         else "retry or reject it in Approvals."),
            "/hr/approvals", d.updated_at, a.id if a else None, a.candidate.full_name if a else None)
    acks = {r.item_key: r for r in db.scalars(select(ReviewAck).where(ReviewAck.item_key.in_([i["key"] for i in items])))}
    names = dict(db.execute(select(User.id, User.full_name).where(User.id.in_({r.acked_by for r in acks.values()}))).all()) if acks else {}
    for i in items:
        r = acks.get(i["key"])
        i["ack"] = {"by": names.get(r.acked_by), "at": r.acked_at, "note": r.note} if r else None
    order = {"high": 0, "medium": 1, "low": 2}
    items.sort(key=lambda i: (i["ack"] is not None, order[i["severity"]], -(i["at"].timestamp() if i["at"] else 0)))
    return items


# ---- talent pool ---------------------------------------------------------------------------


def candidates(db: Session, job_ids: list[str] | None, q: str, stage: str | None) -> list[dict]:
    jobs = scoped_jobs(db, job_ids)
    titles = {j.id: j.title for j in jobs}
    apps = _apps(db, jobs)
    stages = bulk_stages(db, apps)
    evs = {e.application_id: e for e in db.scalars(select(Evaluation).where(
        Evaluation.application_id.in_([a.id for a in apps]), Evaluation.review_state != "superseded"))} if apps else {}
    msg_counts = Counter(db.scalars(select(InboxMessage.application_id).where(
        InboxMessage.application_id.in_([a.id for a in apps])))) if apps else Counter()
    people: dict[str, dict] = {}
    for a in sorted(apps, key=lambda x: x.submitted_at, reverse=True):
        u = a.candidate
        p = people.setdefault(u.id, {"id": u.id, "name": u.full_name, "email": u.email, "applications": [],
                                     "last_activity": a.updated_at, "messages": 0})
        ev = evs.get(a.id)
        p["applications"].append({
            "id": a.id, "job": {"id": a.job_id, "title": titles[a.job_id]}, "stage": stages[a.id],
            "stage_label": STAGE_LABEL[stages[a.id]], "submitted_at": a.submitted_at,
            "evaluation": {"state": ev.review_state, "source": ev.source,
                           "flagged": INJECTION in (ev.review_flags or [])} if ev else None,
            "contact_status": a.contact_status, "parse_status": a.document.parse_status,
        })
        p["messages"] += msg_counts[a.id]
        p["last_activity"] = max(p["last_activity"], a.updated_at)
    out = list(people.values())
    if q:
        ql = q.lower()
        out = [p for p in out if ql in p["name"].lower() or ql in p["email"].lower()]
    if stage:
        out = [p for p in out if any(x["stage"] == stage for x in p["applications"])]
    out.sort(key=lambda p: p["last_activity"], reverse=True)
    return out


def candidate_detail(db: Session, job_ids: list[str] | None, user_id: str) -> dict | None:
    rows = [p for p in candidates(db, job_ids, "", None) if p["id"] == user_id]
    if not rows:
        return None
    person = rows[0]
    app_ids = [a["id"] for a in person["applications"]]
    msgs = list(db.scalars(select(InboxMessage).where(InboxMessage.application_id.in_(app_ids))
                           .order_by(InboxMessage.received_at.desc())))
    drafts = list(db.scalars(select(EmailDraft).where(EmailDraft.application_id.in_(app_ids))
                             .order_by(EmailDraft.created_at.desc())))
    interviews = db.execute(select(Interview, InterviewSlot).join(InterviewSlot, InterviewSlot.id == Interview.slot_id)
                            .where(Interview.application_id.in_(app_ids))).all()
    events = list(db.scalars(select(AuditEvent).where(AuditEvent.target_id.in_(app_ids + [d.id for d in drafts]))
                             .order_by(AuditEvent.at.desc()).limit(60)))
    person.update({
        "messages_list": [{"id": m.id, "subject": m.subject, "received_at": m.received_at, "status": m.status,
                           "category": m.category, "summary": m.summary} for m in msgs],
        "emails": [{"id": d.id, "kind": d.kind, "status": d.status, "subject": d.subject, "created_at": d.created_at,
                    "approved_at": d.approved_at} for d in drafts],
        "interviews": [{"id": iv.id, "status": iv.status, "starts_at": sl.starts_at, "ends_at": sl.ends_at,
                        "application_id": iv.application_id} for iv, sl in interviews],
        "timeline": [{"at": e.at, "action": e.action, "actor_role": e.actor_role, "outcome": e.outcome} for e in events],
    })
    return person


# ---- shortlist report --------------------------------------------------------------------------


def shortlist_report(db: Session, job: Job) -> dict:
    rubric = current_rubric(db, job)
    sl = approved_shortlist(db, job.id)
    wrev = current_weights(db, job)
    out = {"job": {"id": job.id, "title": job.title, "location": job.location, "summary": job.summary},
           "generated_at": utcnow(), "rubric": rubric.criteria if rubric else [],
           "rubric_revision": rubric.revision if rubric else None,
           "weights": (wrev.weights if wrev else {}), "shortlist": None, "members": []}
    if sl is None or rubric is None:
        return out
    approver = db.get(User, sl.approved_by) if sl.approved_by else None
    out["shortlist"] = {"id": sl.id, "revision": sl.revision, "digest": sl.digest, "approved_at": sl.approved_at,
                        "approved_by": approver.full_name if approver else None,
                        "rubric_revision": sl.rubric_revision, "weights_revision": sl.weights_revision}
    weights = wrev.weights if wrev else {}
    for m in sl.members:
        a = db.get(Application, m["application_id"])
        ev = db.scalar(select(Evaluation).where(Evaluation.application_id == a.id, Evaluation.review_state != "superseded")
                       .order_by(Evaluation.created_at.desc()))
        crit = []
        score = None
        if ev and (ev.result or {}).get("criteria"):
            by_id = {c["criterion_id"]: c for c in ev.result["criteria"]}
            score = score_evaluation(ev.result, rubric.criteria, weights) if ev.rubric_revision == rubric.revision else None
            for c in rubric.criteria:
                r = by_id.get(c["id"], {})
                crit.append({"id": c["id"], "label": c["label"], "required": c.get("required", False),
                             "rating": r.get("rating"), "status": r.get("status", "unknown"),
                             "explanation": r.get("explanation", ""), "evidence": r.get("evidence", [])[:2],
                             "unknowns": r.get("unknowns", [])[:2]})
        out["members"].append({
            "application_id": a.id, "name": a.candidate.full_name, "in_proposal": m["in_proposal"],
            "override_reason": m.get("override_reason", ""), "position": m.get("position"),
            "lower": score["lower"] if score else m.get("lower"), "upper": score["upper"] if score else m.get("upper"),
            "coverage": score["coverage"] if score else m.get("coverage"),
            "source": ev.source if ev else None, "model_id": ev.model_id if ev else None,
            "flags": ev.review_flags if ev else [], "summary": (ev.result or {}).get("job_related_summary", "") if ev else "",
            "criteria": crit,
        })
    return out


def median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None

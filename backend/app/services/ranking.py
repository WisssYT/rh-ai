"""Deterministic scoring (no LLM calls) and shortlist snapshots."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..deps import Principal, audit
from ..models import Application, Approval, Evaluation, Job, RubricRevision, Shortlist, WeightsRevision, utcnow
from ..security import digest
from .evaluation import normalize_weights

NEAR_TIE_POINTS = 3.0


def current_weights(db: Session, job: Job) -> WeightsRevision | None:
    if job.current_weights_revision is None:
        return None
    return db.scalar(
        select(WeightsRevision).where(
            WeightsRevision.job_id == job.id, WeightsRevision.revision == job.current_weights_revision
        )
    )


def score_evaluation(result: dict, criteria: list[dict], weights: dict[str, float]) -> dict:
    """lower = sum(w * r/4) over assessed criteria; upper = lower + weights of unknown criteria.

    Known criteria are NOT renormalized: a mostly empty CV cannot reach a misleading perfect score.
    """
    by_id = {c["criterion_id"]: c for c in result.get("criteria", [])}
    lower, unknown_w, known_w = 0.0, 0.0, 0.0
    per = []
    unresolved_required = []
    for c in criteria:
        w = float(weights.get(c["id"], 0.0))
        r = by_id.get(c["id"])
        if r and r.get("status") == "supported" and r.get("rating") is not None:
            contrib = w * r["rating"] / 4.0
            lower += contrib
            known_w += w
            per.append({"criterion_id": c["id"], "weight": w, "rating": r["rating"], "contribution": round(contrib, 2)})
        else:
            unknown_w += w
            per.append({"criterion_id": c["id"], "weight": w, "rating": None, "contribution": 0.0})
            if c.get("required"):
                unresolved_required.append(c["id"])
    total_w = sum(float(weights.get(c["id"], 0.0)) for c in criteria) or 100.0
    return {
        "lower": round(lower * 100 / total_w, 2),
        "upper": round((lower + unknown_w) * 100 / total_w, 2),
        "coverage": round(known_w * 100 / total_w, 1),
        "per_criterion": per,
        "unresolved_required": unresolved_required,
        # "score" equals lower only when coverage is complete
        "complete": unknown_w == 0,
    }


def compute_ranking(db: Session, job: Job, weights_override: dict[str, float] | None = None) -> dict:
    rubric = db.scalar(
        select(RubricRevision).where(
            RubricRevision.job_id == job.id, RubricRevision.revision == job.current_rubric_revision
        )
    )
    if rubric is None:
        return {"rubric_revision": None, "rows": [], "proposed": [], "review": [], "cutoff": None}
    wrev = current_weights(db, job)
    weights = normalize_weights(weights_override) if weights_override else (wrev.weights if wrev else {})
    criteria = rubric.criteria
    apps = list(
        db.scalars(
            select(Application).where(Application.job_id == job.id, Application.status == "submitted")
            .order_by(Application.submitted_at, Application.id)
        )
    )
    evals = {
        e.application_id: e
        for e in db.scalars(
            select(Evaluation).where(Evaluation.job_id == job.id, Evaluation.review_state != "superseded")
        )
    }
    rows = []
    for a in apps:
        ev = evals.get(a.id)
        row = {
            "application_id": a.id,
            "candidate_name": a.candidate.full_name,
            "submitted_at": a.submitted_at,
            "contact_status": a.contact_status,
            "parse_status": a.document.parse_status,
            "evaluation_id": ev.id if ev else None,
            "evaluation_state": ev.review_state if ev else "not_evaluated",
            "evaluation_source": ev.source if ev else None,
            "stale": bool(ev and ev.rubric_revision != rubric.revision),
            "review_flags": ev.review_flags if ev else [],
            "summary": (ev.result or {}).get("job_related_summary", "") if ev else "",
        }
        usable = ev is not None and ev.review_state in ("provisional", "needs_review") and not row["stale"] \
            and ev.result.get("criteria")
        if usable:
            row.update(score_evaluation(ev.result, criteria, weights))
        else:
            row.update({"lower": None, "upper": None, "coverage": 0.0, "per_criterion": [],
                        "unresolved_required": [], "complete": False})
        rows.append(row)

    scored = [r for r in rows if r["lower"] is not None]
    unscored = [r for r in rows if r["lower"] is None]
    scored.sort(key=lambda r: (-r["lower"], -r["upper"], str(r["submitted_at"]), r["application_id"]))
    for i, r in enumerate(scored, start=1):
        r["position"] = i
        prev = scored[i - 2] if i > 1 else None
        nxt = scored[i] if i < len(scored) else None
        r["near_tie"] = any(o is not None and abs(o["lower"] - r["lower"]) < NEAR_TIE_POINTS for o in (prev, nxt))
    for r in unscored:
        r["position"] = None
        r["near_tie"] = False

    # Only applicants with actual assessed evidence can be proposed; unknown is routed to review instead.
    eligible = [r for r in scored if r["coverage"] > 0 and r["lower"] > 0 and r["lower"] >= job.min_suggest_score]
    proposed = eligible[: job.shortlist_size]
    proposed_ids = {r["application_id"] for r in proposed}
    cutoff = proposed[-1]["lower"] if len(proposed) == job.shortlist_size else float(job.min_suggest_score)
    review = []
    for r in rows:
        reasons = []
        if r["application_id"] not in proposed_ids and r["upper"] is not None and r["upper"] >= cutoff:
            reasons.append("could cross the cutoff once unknown criteria are resolved")
        if r["unresolved_required"]:
            reasons.append("required criteria unresolved: " + ", ".join(r["unresolved_required"]))
        if r["evaluation_state"] in ("needs_review", "invalid"):
            reasons.append(f"evaluation {r['evaluation_state'].replace('_', ' ')}")
        if r["evaluation_state"] == "not_evaluated":
            reasons.append("not evaluated yet")
        if r["stale"]:
            reasons.append("evaluation is stale (rubric changed)")
        if r["parse_status"] != "parsed":
            reasons.append("document needs manual review")
        if any(f == "possible_prompt_injection" for f in r["review_flags"]):
            reasons.append("suspicious instruction-like content in CV")
        r["proposed"] = r["application_id"] in proposed_ids
        r["review_reasons"] = reasons
        if reasons:
            review.append(r["application_id"])
    return {
        "job_id": job.id,
        "rubric_revision": rubric.revision,
        "weights_revision": wrev.revision if wrev else None,
        "weights": weights,
        "weights_preview": weights_override is not None,
        "criteria": [{k: c[k] for k in ("id", "label", "required")} for c in criteria],
        "order_label": "Provisional evidence-based order (lower-bound evidence score). Not a hiring decision.",
        "shortlist_size": job.shortlist_size,
        "min_suggest_score": job.min_suggest_score,
        "cutoff": cutoff,
        "rows": scored + unscored,
        "proposed": [r["application_id"] for r in proposed],
        "review": review,
        "llm_calls": 0,
    }


def shortlist_digest(sl: Shortlist) -> str:
    return digest(
        {"job": sl.job_id, "rev": sl.revision, "members": sorted(m["application_id"] for m in sl.members),
         "rubric": sl.rubric_revision, "weights": sl.weights_revision}
    )


def latest_shortlist(db: Session, job_id: str) -> Shortlist | None:
    return db.scalar(select(Shortlist).where(Shortlist.job_id == job_id).order_by(Shortlist.revision.desc()))


def approved_shortlist(db: Session, job_id: str) -> Shortlist | None:
    return db.scalar(
        select(Shortlist).where(Shortlist.job_id == job_id, Shortlist.status == "human_approved")
        .order_by(Shortlist.revision.desc())
    )


def save_shortlist_draft(db: Session, p: Principal, job: Job, members: list[dict]) -> Shortlist:
    ranking = compute_ranking(db, job)
    if ranking["rubric_revision"] is None:
        raise HTTPException(409, "No approved rubric")
    by_id = {r["application_id"]: r for r in ranking["rows"]}
    proposed = set(ranking["proposed"])
    seen, out = set(), []
    for m in members:
        aid = m["application_id"]
        if aid in seen:
            continue
        seen.add(aid)
        r = by_id.get(aid)
        if r is None:
            raise HTTPException(422, "Shortlist contains an application that is not part of this job")
        reason = (m.get("override_reason") or "").strip()[:300]
        if aid not in proposed and not reason:
            raise HTTPException(422, f"Include an override reason for {r['candidate_name']} (outside the proposal)")
        out.append(
            {
                "application_id": aid,
                "candidate_name": r["candidate_name"],
                "in_proposal": aid in proposed,
                "position": r["position"],
                "lower": r["lower"],
                "upper": r["upper"],
                "coverage": r["coverage"],
                "override_reason": reason,
            }
        )
    excluded = proposed - seen
    prev = latest_shortlist(db, job.id)
    sl = Shortlist(
        job_id=job.id,
        revision=(prev.revision + 1) if prev else 1,
        status="draft",
        members=out,
        rubric_revision=ranking["rubric_revision"],
        weights_revision=ranking["weights_revision"] or 0,
        created_by=p.id,
    )
    sl.digest = shortlist_digest(sl)
    db.add(sl)
    db.flush()
    audit(db, p, "shortlist.draft_saved", "shortlist", sl.id, job_id=job.id, revision=sl.revision,
          digest=sl.digest, details={"members": len(out), "excluded_from_proposal": len(excluded),
                                     "overrides": sum(1 for m in out if not m["in_proposal"])})
    return sl


def approve_shortlist(db: Session, p: Principal, job: Job, shortlist_id: str, reviewed_digest: str) -> Shortlist:
    # job row is locked by the caller (get_job_for_staff(lock=True)) -> atomic compare
    sl = db.get(Shortlist, shortlist_id, with_for_update=True)
    if sl is None or sl.job_id != job.id:
        raise HTTPException(404, "Shortlist not found")
    latest = latest_shortlist(db, job.id)
    if sl.status != "draft" or latest.id != sl.id:
        raise HTTPException(409, "Stale shortlist: a newer revision exists or it is already decided")
    if sl.digest != reviewed_digest or shortlist_digest(sl) != reviewed_digest:
        raise HTTPException(409, "Stale shortlist: the reviewed content no longer matches")
    if sl.rubric_revision != job.current_rubric_revision or sl.weights_revision != (job.current_weights_revision or 0):
        raise HTTPException(409, "Stale shortlist: rubric or weights changed since this draft was saved")
    if not sl.members:
        raise HTTPException(422, "An empty shortlist cannot be approved")
    for old in db.scalars(select(Shortlist).where(Shortlist.job_id == job.id, Shortlist.status == "human_approved")):
        old.status = "superseded"
    sl.status, sl.approved_by, sl.approved_at = "human_approved", p.id, utcnow()
    db.add(Approval(action="approve_shortlist", target_type="shortlist", target_id=sl.id, target_revision=sl.revision,
                    digest=sl.digest, approver_id=p.id, approver_role=p.role))
    audit(db, p, "shortlist.approved", "shortlist", sl.id, job_id=job.id, revision=sl.revision, digest=sl.digest,
          details={"members": len(sl.members)})
    return sl

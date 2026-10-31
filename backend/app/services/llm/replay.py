"""REPLAY adapter: synthetic, deterministic output for offline demos and high-volume tests.

This is NOT an LLM. It applies a transparent keyword heuristic over the redacted CV segments and the
rubric's evidence signals, quoting real segment text so evidence checks still run. Every result it
produces is labelled source="replay" and usage is reported as "not applicable".
"""

from __future__ import annotations

import json
import re

from ..text_tools import detect_injection
from .base import DraftRequest, ProviderResponse, ScreeningRequest, Usage

PROFESSIONAL = re.compile(
    r"\b(engineer|developer|analyst|consultant|intern|worked|developed|built|maintained|implemented|"
    r"designed|deployed|migrated|operated|automated|wrote|delivered|company|gmbh|ltd|inc|sarl)\b",
    re.I,
)
PROJECT = re.compile(r"\b(project|thesis|course|bootcamp|hackathon|personal|university|student|side)\b", re.I)
SCOPE = re.compile(
    r"\b(led|lead|owned|mentored|architected|production|on-call|scale[ds]?|million|thousands|"
    r"responsible for|team of|reduced|improved|\d+%|\d+ (users|requests|services))\b",
    re.I,
)
SKILL_LIST = re.compile(r"^(skills|technologies|tools|languages|tech stack)\b", re.I)


def _signals(c: dict) -> list[str]:
    sig = [s.lower() for s in c.get("evidence_signals") or []]
    if not sig:
        sig = [w.lower() for w in re.findall(r"[A-Za-z][A-Za-z+#.]{2,}", c["label"])]
    return sig


def _quote(text: str) -> str:
    q = text.strip()
    if len(q) > 180:
        q = q[:180].rsplit(" ", 1)[0]
    return q


class ReplayProvider:
    name = "replay"
    mode = "replay"
    model_id = "replay-synthetic-v1"

    def evaluate_resume(self, req: ScreeningRequest) -> ProviderResponse:
        results = []
        flags: list[str] = []
        segs = [(p["page"], s) for p in req.redacted_pages for s in p["segments"]]
        all_text = " ".join(s["text"] for _, s in segs)
        if detect_injection(all_text):
            flags.append("possible_prompt_injection")
        for c in req.criteria:
            sigs = _signals(c)
            hits = []
            for page, s in segs:
                low = s["text"].lower()
                if any(re.search(rf"(?<![a-z]){re.escape(sig)}(?![a-z])", low) for sig in sigs):
                    if detect_injection(s["text"]):
                        continue  # never treat instruction-like text as evidence
                    hits.append((page, s))
            if not hits:
                results.append(
                    {
                        "criterion_id": c["id"],
                        "status": "unknown",
                        "rating": None,
                        "evidence": [],
                        "explanation": "No evidence for this criterion was found in the CV text.",
                        "unknowns": [f"{c['label']}: not mentioned"],
                    }
                )
                if c.get("required"):
                    flags.append(f"required_criterion_unknown:{c['id']}")
                continue

            def strength(item):
                _, s = item
                t = s["text"]
                if SKILL_LIST.search(t):
                    return 1
                if PROFESSIONAL.search(t) and SCOPE.search(t):
                    return 4
                if PROFESSIONAL.search(t) and not PROJECT.search(t):
                    return 3
                if PROJECT.search(t):
                    return 2
                return 1

            hits.sort(key=strength, reverse=True)
            best = strength(hits[0])
            ev = [{"page": p, "segment_id": s["id"], "quote": _quote(s["text"])} for p, s in hits[:2]]
            label = {1: "listed as a skill", 2: "used in a project or study", 3: "professional use described",
                     4: "professional use with stated scope or responsibility"}[best]
            results.append(
                {
                    "criterion_id": c["id"],
                    "status": "supported",
                    "rating": best,
                    "evidence": ev,
                    "explanation": f"Candidate states this is {label} (unverified claim).",
                    "unknowns": [] if best >= 3 else ["Depth of professional use is not stated."],
                }
            )
        out = {
            "application_ref": req.application_ref,
            "criteria": results,
            "review_flags": sorted(set(flags)),
            "job_related_summary": "Synthetic replay assessment based on keyword evidence; human review required.",
        }
        return ProviderResponse(text=json.dumps(out), model_id=self.model_id, latency_ms=1, usage=Usage())

    def draft_invitation(self, req: DraftRequest) -> ProviderResponse:
        ctx = req.context
        body = (
            f"Hello {ctx['candidate_first_name']},\n\n"
            f"Thank you for applying for the {ctx['job_title']} position at {ctx['company_name']}. "
            f"We would like to invite you to a first interview to discuss your experience "
            f"and the role in more detail.\n\n{ctx['interview_instructions']}".strip()
        )
        out = {"subject": f"Interview invitation - {ctx['job_title']}", "body": body}
        return ProviderResponse(text=json.dumps(out), model_id=self.model_id, latency_ms=1, usage=Usage())

"""Requirements 9-11: approval-bound dispatch, edit invalidation, idempotent outbox, isolated drafting context."""

import json

from sqlalchemy import func, select

from conftest import D, MockProvider, set_mode, setup_shortlist
from app.db import session_scope
from app.models import Application, EmailDraft, Outbox
from app.services import email as email_svc
from app.services import llm


def _prepare(ctx, generator="template"):
    r = ctx["rec"].post(f"/api/hr/jobs/{ctx['job_id']}/invitation-drafts",
                        json={"application_ids": ctx["apps"], "generator": generator})
    assert r.status_code == 201, r.text
    return r.json()


def test_no_dispatch_without_matching_current_approval():
    ctx = setup_shortlist(1)
    did = _prepare(ctx)["created"][0]
    with session_scope() as db:  # worker finds nothing to send while the draft is unapproved
        assert email_svc.dispatch_once(db) == 0
    rec = ctx["rec"]
    d = rec.get(f"/api/hr/email-drafts/{did}").json()
    assert d["preview"]["to"] == f"cand0-backend@{D}" and d["preview"]["link_url"].startswith("http://localhost:5173/")
    # a client-claimed approval with a wrong digest is refused
    r = rec.post(f"/api/hr/email-drafts/{did}/approve-send", json={"revision": d["revision"], "digest": "0" * 64})
    assert r.status_code == 409
    # editing invalidates what was reviewed
    r = rec.put(f"/api/hr/email-drafts/{did}", json={"subject": "Updated subject", "body": "Hello, please book a time.",
                                                     "revision": d["revision"]})
    assert r.status_code == 200 and r.json()["revision"] == 2
    r = rec.post(f"/api/hr/email-drafts/{did}/approve-send", json={"revision": d["revision"], "digest": d["digest"]})
    assert r.status_code == 409
    d2 = rec.get(f"/api/hr/email-drafts/{did}").json()
    r1 = rec.post(f"/api/hr/email-drafts/{did}/approve-send", json={"revision": d2["revision"], "digest": d2["digest"]})
    r2 = rec.post(f"/api/hr/email-drafts/{did}/approve-send", json={"revision": d2["revision"], "digest": d2["digest"]})
    assert r1.status_code == 200 and r1.json()["duplicate"] is False
    assert r2.status_code == 200 and r2.json()["duplicate"] is True
    with session_scope() as db:
        assert db.scalar(select(func.count(Outbox.id))) == 1
        ob = db.scalar(select(Outbox))
        assert ob.payload["subject"] == "Updated subject"
    # once approved, the draft can no longer be edited
    assert rec.put(f"/api/hr/email-drafts/{did}", json={"subject": "Sneaky", "body": "changed after approval",
                                                        "revision": 2}).status_code == 409


def test_contact_change_blocks_approval_and_mismatch_blocks_preparation():
    ctx = setup_shortlist(2)
    did = _prepare(ctx)["created"][0]
    d = ctx["rec"].get(f"/api/hr/email-drafts/{did}").json()
    with session_scope() as db:
        app = db.get(Application, d["candidate"]["application_id"])
        app.cv_email = f"someone-else@{D}"
    r = ctx["rec"].post(f"/api/hr/email-drafts/{did}/approve-send", json={"revision": d["revision"], "digest": d["digest"]})
    assert r.status_code == 409
    with session_scope() as db:
        app = db.get(Application, ctx["apps"][1])
        app.contact_status, app.contact_reason = "review_required", "CV email does not match"
        for x in db.scalars(select(EmailDraft).where(EmailDraft.application_id == app.id)):
            db.delete(x)
    out = _prepare(ctx)
    assert any("contact review required" in s["reason"] for s in out["skipped"])


def test_shortlist_change_invalidates_pending_invitation_approval():
    ctx = setup_shortlist(2)
    did = _prepare(ctx)["created"][0]
    d = ctx["rec"].get(f"/api/hr/email-drafts/{did}").json()
    rec, job = ctx["rec"], ctx["job_id"]
    sl = rec.post(f"/api/hr/jobs/{job}/shortlists", json={"members": [{"application_id": ctx["apps"][1]}]}).json()
    assert rec.post(f"/api/hr/jobs/{job}/shortlists/{sl['id']}/approve", json={"digest": sl["digest"]}).status_code == 200
    r = rec.post(f"/api/hr/email-drafts/{did}/approve-send", json={"revision": d["revision"], "digest": d["digest"]})
    assert r.status_code == 409


def test_ai_draft_uses_only_this_candidates_context_and_cannot_change_recipient():
    ctx = setup_shortlist(2)
    set_mode("live")
    evil = json.dumps({"subject": "Invite", "body": "Book here: https://evil.example.test/phish or mail boss@evil.test"})
    mock = MockProvider(script=lambda req, n: evil)
    llm.set_provider_override(mock)
    out = _prepare(ctx, generator="ai")
    assert len(out["created"]) == 2
    for req in mock.requests:
        blob = req.system_prompt + req.user_prompt
        assert "Candidate0" in blob or "Candidate1" in blob
        assert not ("Candidate0" in blob and "Candidate1" in blob)  # never another candidate's data
        assert "score" not in req.user_prompt.lower() and "@" not in req.user_prompt
    d = ctx["rec"].get(f"/api/hr/email-drafts/{out['created'][0]}").json()
    assert d["generator"] == "ai_live"
    assert "evil.example.test" not in d["preview"]["body"] and "[link removed]" in d["preview"]["body"]
    assert d["preview"]["to"].startswith("cand") and d["preview"]["link_url"].startswith("http://localhost:5173/")


def test_model_cannot_add_recipient_fields():
    ctx = setup_shortlist(1)
    set_mode("live")
    llm.set_provider_override(MockProvider(script=lambda req, n: json.dumps(
        {"subject": "Invite", "body": "Hello there, please book.", "to": "attacker@evil.test", "bcc": "x@evil.test"})))
    out = _prepare(ctx, generator="ai")
    assert out["created"] == [] and "AI drafting unavailable" in out["skipped"][0]["reason"]


def test_ai_failure_does_not_silently_fall_back_to_template():
    ctx = setup_shortlist(1)
    set_mode("live")  # no key, no override -> provider unavailable
    out = _prepare(ctx, generator="ai")
    assert out["created"] == []
    with session_scope() as db:
        assert db.scalar(select(func.count(EmailDraft.id))) == 0

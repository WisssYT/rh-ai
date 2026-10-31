"""Requirement 16: approved end-to-end flow delivers to Mailpit and records the human-approved interview."""

import json
import urllib.request

import pytest
from sqlalchemy import select

from conftest import D, add_slots, send_invitations, setup_shortlist
from app.config import get_settings
from app.db import session_scope
from app.models import Approval, AuditEvent, Interview
from app.services import email as email_svc


def _mailpit(query: str):
    base = get_settings().mailpit_ui_url
    with urllib.request.urlopen(f"{base}/api/v1/search?query={query}", timeout=3) as r:
        return json.loads(r.read())


@pytest.fixture
def mailpit():
    try:
        _mailpit("x")
    except OSError:
        pytest.skip("Mailpit is not running on SMTP_PORT/MAILPIT_UI_URL")


def test_end_to_end_invite_book_confirm(mailpit):
    ctx = setup_shortlist(1, slug="e2e")
    inv = send_invitations(ctx)[0]
    to = f"cand0-e2e@{D}"
    msgs = _mailpit(f"to:{to}")["messages"]
    assert any("Interview invitation" in m["Subject"] for m in msgs)
    slot = add_slots(ctx, 1)[0]
    cand, rec = ctx["cands"][0], ctx["rec"]
    slots = cand.get(f"/api/candidate/invitations/{inv}/slots").json()
    assert [s["id"] for s in slots["slots"]] == [slot] and slots["timezone"] == "Africa/Tunis"
    b = cand.post(f"/api/candidate/invitations/{inv}/booking-requests",
                  json={"slot_id": slot, "idempotency_key": "e2e-booking-1"}).json()["booking"]
    r = rec.post(f"/api/hr/booking-requests/{b['id']}/confirm", json={"note": "see you"}).json()
    d = rec.post(f"/api/hr/interviews/{r['interview_id']}/confirmation-draft").json()
    assert d["status"] == "draft" and "Africa/Tunis" in d["preview"]["body"]
    with session_scope() as db:
        assert email_svc.dispatch_once(db) == 0  # nothing leaves before approval
    rec.post(f"/api/hr/email-drafts/{d['id']}/approve-send", json={"revision": d["revision"], "digest": d["digest"]})
    with session_scope() as db:
        assert email_svc.dispatch_once(db) == 1
    assert any("Interview confirmed" in m["Subject"] for m in _mailpit(f"to:{to}")["messages"])
    with session_scope() as db:
        iv = db.get(Interview, r["interview_id"])
        assert iv.status == "confirmed" and iv.confirmed_by == ctx["rec_id"]
        actions = {a.action for a in db.scalars(select(Approval))}
        assert {"authorize_analysis_run", "approve_shortlist", "approve_send_invitation",
                "approve_send_confirmation"} <= actions
        audit = [a.action for a in db.scalars(select(AuditEvent))]
        assert "booking.confirmed" in audit and audit.count("email.sent") == 2
    assert cand.get("/api/candidate/applications").json()["items"][0]["stage"] == "interview_confirmed"

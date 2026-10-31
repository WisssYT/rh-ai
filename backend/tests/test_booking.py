"""Requirements 12-14: one hold per slot under concurrency, idempotent retries, invitation binding, HR confirmation."""

import threading
from datetime import timedelta

from sqlalchemy import func, select

from conftest import D, Client, add_slots, register, send_invitations, setup_shortlist
from app.db import session_scope
from app.models import BookingRequest, Interview, InterviewSlot, Invitation, utcnow
from app.services import booking


def test_two_simultaneous_requests_one_slot_exactly_one_hold():
    ctx = setup_shortlist(2)
    invs = send_invitations(ctx)
    slot = add_slots(ctx, 2)[0]
    results = []
    barrier = threading.Barrier(2)

    def go(c, inv, key):
        barrier.wait()
        r = c.post(f"/api/candidate/invitations/{inv}/booking-requests", json={"slot_id": slot, "idempotency_key": key})
        results.append(r)

    ts = [threading.Thread(target=go, args=(ctx["cands"][i], invs[i], f"key-{i}-abcdef")) for i in range(2)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    codes = sorted(r.status_code for r in results)
    assert codes == [201, 409], [r.text for r in results]
    loser = next(r for r in results if r.status_code == 409).json()["detail"]
    assert "alternatives" in loser and all(a["id"] != slot for a in loser["alternatives"])
    with session_scope() as db:
        assert db.scalar(select(func.count(BookingRequest.id)).where(BookingRequest.slot_id == slot)) == 1


def test_retry_is_idempotent_and_one_active_request_per_invitation():
    ctx = setup_shortlist(1)
    inv = send_invitations(ctx)[0]
    s1, s2 = add_slots(ctx, 2)
    c = ctx["cands"][0]
    a = c.post(f"/api/candidate/invitations/{inv}/booking-requests", json={"slot_id": s1, "idempotency_key": "retry-key-1"})
    b = c.post(f"/api/candidate/invitations/{inv}/booking-requests", json={"slot_id": s1, "idempotency_key": "retry-key-1"})
    assert a.status_code == 201 and b.status_code == 201 and b.json()["created"] is False
    assert a.json()["booking"]["id"] == b.json()["booking"]["id"]
    other = c.post(f"/api/candidate/invitations/{inv}/booking-requests", json={"slot_id": s2, "idempotency_key": "another-key"})
    assert other.status_code == 409


def test_wrong_account_expired_or_revoked_invitation_cannot_book():
    ctx = setup_shortlist(2)
    invs = send_invitations(ctx)
    slot = add_slots(ctx, 1)[0]
    intruder = register("Mallory Example", f"mallory@{D}")
    assert intruder.get(f"/api/candidate/invitations/{invs[0]}/slots").status_code == 404
    assert intruder.post(f"/api/candidate/invitations/{invs[0]}/booking-requests",
                         json={"slot_id": slot, "idempotency_key": "intruder-key"}).status_code == 404
    assert ctx["cands"][1].get(f"/api/candidate/invitations/{invs[0]}/slots").status_code == 404  # other invitee
    assert Client().get(f"/api/candidate/invitations/{invs[0]}/slots").status_code == 401  # link alone is no login
    with session_scope() as db:
        db.get(Invitation, invs[0]).expires_at = utcnow() - timedelta(minutes=1)
    assert ctx["cands"][0].get(f"/api/candidate/invitations/{invs[0]}/slots").status_code == 410
    assert ctx["rec"].post(f"/api/hr/invitations/{invs[1]}/revoke").status_code == 200
    r = ctx["cands"][1].post(f"/api/candidate/invitations/{invs[1]}/booking-requests",
                             json={"slot_id": slot, "idempotency_key": "revoked-key"})
    assert r.status_code in (404, 410)
    with session_scope() as db:
        assert db.scalar(select(func.count(BookingRequest.id))) == 0


def test_request_stays_provisional_until_hr_confirms_and_expired_hold_cannot_be_confirmed():
    ctx = setup_shortlist(2)
    invs = send_invitations(ctx)
    s1, s2 = add_slots(ctx, 2)
    c0, c1 = ctx["cands"]
    b0 = c0.post(f"/api/candidate/invitations/{invs[0]}/booking-requests",
                 json={"slot_id": s1, "idempotency_key": "confirm-me-1"}).json()["booking"]
    assert b0["status"] == "requested"
    with session_scope() as db:
        assert db.scalar(select(func.count(Interview.id))) == 0
        assert db.get(InterviewSlot, s1).status == "held"
    assert c0.post(f"/api/hr/booking-requests/{b0['id']}/confirm", json={}).status_code == 403  # candidate can't confirm
    r = ctx["rec"].post(f"/api/hr/booking-requests/{b0['id']}/confirm", json={})
    assert r.status_code == 200 and r.json()["status"] == "confirmed" and r.json()["interview_id"]
    assert ctx["rec"].post(f"/api/hr/booking-requests/{b0['id']}/confirm", json={}).status_code == 200  # idempotent
    with session_scope() as db:
        assert db.scalar(select(func.count(Interview.id))) == 1
    # expired hold
    b1 = c1.post(f"/api/candidate/invitations/{invs[1]}/booking-requests",
                 json={"slot_id": s2, "idempotency_key": "expire-me-1"}).json()["booking"]
    with session_scope() as db:
        db.get(BookingRequest, b1["id"]).hold_expires_at = utcnow() - timedelta(seconds=1)
    r = ctx["rec"].post(f"/api/hr/booking-requests/{b1['id']}/confirm", json={})
    assert r.status_code == 409 and "expired" in r.text
    with session_scope() as db:
        assert db.get(BookingRequest, b1["id"]).status == "expired"
        assert db.get(InterviewSlot, s2).status == "available"
        assert db.scalar(select(func.count(Interview.id))) == 1


def test_hold_expiry_sweeper_releases_slot():
    ctx = setup_shortlist(1)
    inv = send_invitations(ctx)[0]
    s1 = add_slots(ctx, 1)[0]
    b = ctx["cands"][0].post(f"/api/candidate/invitations/{inv}/booking-requests",
                             json={"slot_id": s1, "idempotency_key": "sweep-me-12"}).json()["booking"]
    with session_scope() as db:
        assert booking.expire_holds(db, now=utcnow() + timedelta(days=1)) == 1
    with session_scope() as db:
        assert db.get(BookingRequest, b["id"]).status == "expired"
        assert db.get(InterviewSlot, s1).status == "available"


def test_slot_validation_and_interviewer_overlap():
    from datetime import datetime, timezone

    ctx = setup_shortlist(1)
    base = datetime.now(timezone.utc) + timedelta(days=3)
    post = lambda items: ctx["rec"].post("/api/hr/slots", json={"job_id": ctx["job_id"], "slots": items})  # noqa: E731
    iso = lambda d: d.isoformat()  # noqa: E731
    assert post([{"starts_at": iso(base), "ends_at": iso(base)}]).status_code == 422  # zero duration
    assert post([{"starts_at": iso(base), "ends_at": iso(base - timedelta(hours=1))}]).status_code == 422
    past = datetime.now(timezone.utc) - timedelta(days=1)
    assert post([{"starts_at": iso(past), "ends_at": iso(past + timedelta(minutes=30))}]).status_code == 422
    assert post([{"starts_at": iso(base), "ends_at": iso(base + timedelta(minutes=45))}]).status_code == 201
    r = post([{"starts_at": iso(base + timedelta(minutes=30)), "ends_at": iso(base + timedelta(minutes=75))}])
    assert r.status_code == 409

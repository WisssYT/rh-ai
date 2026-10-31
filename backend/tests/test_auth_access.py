"""Requirements 1-3: candidate submission & isolation, role/assignment boundaries, auth hygiene."""

from conftest import D, PW, Client, apply, cv_pdf, make_job, make_staff, register


def test_candidate_submits_pdf_and_sees_only_own_application():
    rid = make_staff(f"rec@{D}")
    job = make_job([rid])
    a = register("Alice Example", f"alice@{D}")
    r = apply(a, job, cv_pdf("Alice Example", f"alice@{D}"))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["contact_status"] == "ok" and body["document"]["parse_status"] == "parsed"
    assert "score" not in str(body).lower()  # candidates never see scores
    b = register("Bob Example", f"bob@{D}")
    apply(b, job, cv_pdf("Bob Example", f"bob@{D}"))
    items = a.get("/api/candidate/applications").json()["items"]
    assert [i["id"] for i in items] == [body["id"]]


def test_candidate_cannot_read_other_candidates_data():
    rid = make_staff(f"rec@{D}")
    job = make_job([rid])
    a = register("Alice Example", f"alice@{D}")
    b = register("Bob Example", f"bob@{D}")
    app_b = apply(b, job, cv_pdf("Bob Example", f"bob@{D}")).json()["id"]
    assert a.get(f"/api/candidate/applications/{app_b}").status_code == 404
    assert a.get(f"/api/candidate/applications/{app_b}/resume").status_code == 404
    assert a.post(f"/api/candidate/applications/{app_b}/withdraw").status_code == 404
    assert a.get("/api/candidate/invitations/doesnotexist/slots").status_code == 404
    assert b.get(f"/api/candidate/applications/{app_b}/resume").status_code == 200


def test_registration_cannot_grant_privileges():
    c = Client()
    r = c.post("/api/auth/register", json={"email": f"evil@{D}", "full_name": "Evil", "password": PW,
                                           "fictional_data_ack": True, "role": "supervisor"})
    assert r.status_code == 422  # extra field rejected outright
    c = register("Plain User", f"plain@{D}")
    assert c.get("/api/auth/me").json()["user"]["role"] == "candidate"
    assert c.get("/api/hr/jobs").status_code == 403
    assert c.get("/api/supervisor/users").status_code == 403


def test_recruiter_scope_and_supervisor_boundary():
    r1 = make_staff(f"r1@{D}")
    make_staff(f"r2@{D}")
    make_staff(f"sup@{D}", role="supervisor")
    job1 = make_job([r1], slug="job-one")
    c2 = Client().login(f"r2@{D}", portal="staff")
    assert c2.get(f"/api/hr/jobs/{job1}").status_code == 404
    assert c2.get(f"/api/hr/jobs/{job1}/applications").status_code == 404
    assert c2.get(f"/api/hr/jobs/{job1}/ranking").status_code == 404
    assert c2.get("/api/supervisor/users").status_code == 403
    assert c2.post("/api/supervisor/users", json={"email": f"x@{D}", "full_name": "X", "password": "x" * 12,
                                                  "role": "supervisor"}).status_code == 403
    c1 = Client().login(f"r1@{D}", portal="staff")
    assert c1.get(f"/api/hr/jobs/{job1}").status_code == 200
    sup = Client().login(f"sup@{D}", portal="staff")
    assert sup.get(f"/api/hr/jobs/{job1}").status_code == 200


def test_csrf_required_and_logout_invalidates_session():
    c = register("Carol Example", f"carol@{D}")
    r = c.c.post("/api/candidate/applications/x/withdraw")  # no CSRF header
    assert r.status_code == 403
    cookie = c.c.cookies.get("td_session")
    assert c.post("/api/auth/logout").status_code == 200
    stale = Client()
    stale.c.cookies.set("td_session", cookie)
    assert stale.get("/api/candidate/applications").status_code == 401


def test_staff_must_use_staff_portal_and_wrong_password_fails():
    make_staff(f"rec@{D}")
    c = Client()
    assert c.post("/api/auth/login", json={"email": f"rec@{D}", "password": PW, "portal": "candidate"}).status_code == 403
    assert c.post("/api/auth/login", json={"email": f"rec@{D}", "password": "wrong-password",
                                           "portal": "staff"}).status_code == 401


def test_candidate_edits_name_and_changes_password_revoking_other_sessions():
    a = register("Alice Example", f"alice@{D}")
    other = Client().login(f"alice@{D}")
    r = a.patch("/api/candidate/profile", json={"full_name": "Alice B. Example"})
    assert r.status_code == 200 and r.json()["full_name"] == "Alice B. Example"
    assert a.patch("/api/candidate/profile", json={"full_name": "X", "email": f"evil@{D}"}).status_code == 422
    assert a.post("/api/candidate/profile/password",
                  json={"current_password": "wrong-one", "new_password": "Another-long-pw-2"}).status_code == 400
    r = a.post("/api/candidate/profile/password", json={"current_password": PW, "new_password": "Another-long-pw-2"})
    assert r.status_code == 200
    assert a.get("/api/candidate/profile").status_code == 200
    assert other.get("/api/candidate/profile").status_code == 401
    Client().login(f"alice@{D}", password="Another-long-pw-2")

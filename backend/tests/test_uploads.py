"""Requirement 4: invalid/oversized/malformed uploads fail safely; unparseable text -> review, not a low score."""

import io

from conftest import D, Client, apply, cv_pdf, make_job, make_staff, register, run_worker
from app.fixtures.cvs import render_pdf
from app.config import get_settings


def _setup():
    rid = make_staff(f"rec@{D}")
    return make_job([rid]), register("Alice Example", f"alice@{D}")


def test_rejects_non_pdf_and_fake_signature():
    job, c = _setup()
    assert apply(c, job, b"hello world", "cv.txt").status_code == 415
    r = apply(c, job, b"MZ\x90\x00 not a pdf at all %%EOF", "cv.pdf")  # .pdf name, wrong magic bytes
    assert r.status_code == 415


def test_rejects_malformed_and_truncated_pdf():
    job, c = _setup()
    good = cv_pdf("Alice Example", f"alice@{D}")
    assert apply(c, job, good[: len(good) // 2], "cv.pdf").status_code == 422  # truncated (no %%EOF)
    junk = b"%PDF-1.7\n" + b"garbage " * 200 + b"\n%%EOF"
    assert apply(c, job, junk, "cv.pdf").status_code == 422


def test_rejects_oversized_while_receiving():
    job, c = _setup()
    big = b"%PDF-1.4\n" + b"0" * (get_settings().max_upload_bytes + 200_000) + b"\n%%EOF"
    r = apply(c, job, big, "cv.pdf")
    assert r.status_code == 413


def test_rejects_too_many_pages():
    job, c = _setup()
    pages = [[f"Page {i}", "Python developer."] for i in range(get_settings().max_pdf_pages + 2)]
    assert apply(c, job, render_pdf(pages), "cv.pdf").status_code == 422


def test_rejects_encrypted_pdf():
    from pypdf import PdfReader, PdfWriter

    job, c = _setup()
    w = PdfWriter()
    for pg in PdfReader(io.BytesIO(cv_pdf("Alice Example", f"alice@{D}"))).pages:
        w.add_page(pg)
    w.encrypt("secret-password")
    buf = io.BytesIO()
    w.write(buf)
    r = apply(c, job, buf.getvalue(), "cv.pdf")
    assert r.status_code == 422 and "Encrypted" in r.text


def test_scanned_pdf_routes_to_review_not_low_score():
    rid = make_staff(f"rec@{D}")
    job = make_job([rid])
    c = register("Scan Person", f"scan@{D}")
    r = apply(c, job, render_pdf([["x"]], scanned=True), "scan.pdf")
    assert r.status_code == 201
    app_id = r.json()["id"]
    assert r.json()["document"]["parse_status"] == "needs_review"
    assert r.json()["contact_status"] == "review_required"
    rec = Client().login(f"rec@{D}", portal="staff")
    assert rec.post(f"/api/hr/jobs/{job}/analysis-runs", json={"application_ids": [app_id], "rubric_revision": 1,
                                                               "confirm_scope": True}).status_code == 201
    run_worker()
    rk = rec.get(f"/api/hr/jobs/{job}/ranking").json()
    row = next(x for x in rk["rows"] if x["application_id"] == app_id)
    assert row["evaluation_state"] == "needs_review"
    assert row["coverage"] == 0 and row["upper"] == 100  # unknown, not a fabricated low score
    assert app_id in rk["review"] and app_id not in rk["proposed"]


def test_storage_name_is_server_generated_and_download_is_attachment():
    job, c = _setup()
    r = apply(c, job, cv_pdf("Alice Example", f"alice@{D}"), "../../etc/passwd.pdf")
    assert r.status_code == 201
    assert r.json()["document"]["filename"] == "passwd.pdf"
    dl = c.get(f"/api/candidate/applications/{r.json()['id']}/resume")
    assert dl.status_code == 200
    assert dl.headers["content-disposition"].startswith("attachment")
    assert "sandbox" in dl.headers["content-security-policy"]
    assert dl.headers["x-content-type-options"] == "nosniff"


def test_storage_notice_must_be_acknowledged():
    job, c = _setup()
    r = c.post(f"/api/jobs/{job}/applications", files={"file": ("cv.pdf", cv_pdf("A", f"alice@{D}"), "application/pdf")},
               data={"storage_notice_ack": "false"})
    assert r.status_code == 422

"""Requirements 5-8, 11, 15: authorized scope, strict validation, deterministic reweighting, cache metrics, quota."""

import json

import pytest
from sqlalchemy import func, select

from conftest import D, Client, MockProvider, apply, cv_pdf, make_job, make_staff, register, run_worker, set_mode
from app.db import session_scope
from app.models import AnalysisTask, Evaluation, User
from app.services import llm
from app.services.evaluation import OutputInvalid, parse_and_validate
from app.services.llm.base import QuotaExceeded, Usage
from app.services.text_tools import segment_pages


def _job_with_apps(n=2):
    rid = make_staff(f"rec@{D}")
    job = make_job([rid])
    apps = []
    for i in range(n):
        c = register(f"Cand{i} Example", f"c{i}@{D}")
        apps.append(apply(c, job, cv_pdf(f"Cand{i} Example", f"c{i}@{D}")).json()["id"])
    return job, Client().login(f"rec@{D}", portal="staff"), apps


def _start(rec, job, apps, rev=1):
    return rec.post(f"/api/hr/jobs/{job}/analysis-runs",
                    json={"application_ids": apps, "rubric_revision": rev, "confirm_scope": True})


def test_no_evaluations_without_authorized_run():
    job, rec, apps = _job_with_apps(2)
    run_worker()
    with session_scope() as db:
        assert db.scalar(select(func.count(Evaluation.id))) == 0
    assert rec.post(f"/api/hr/jobs/{job}/analysis-runs",
                    json={"application_ids": apps, "rubric_revision": 1, "confirm_scope": False}).status_code == 422
    assert _start(rec, job, apps, rev=99).status_code == 409  # stale rubric revision
    # scope limited to the selected application
    assert _start(rec, job, apps[:1]).status_code == 201
    run_worker()
    with session_scope() as db:
        evs = list(db.scalars(select(Evaluation)))
        assert [e.application_id for e in evs] == apps[:1]


def test_candidate_cannot_start_analysis_and_foreign_app_rejected():
    job, rec, apps = _job_with_apps(1)
    other_job = make_job([], slug="other")
    c = register("Zed Example", f"zed@{D}")
    other_app = apply(c, other_job, cv_pdf("Zed Example", f"zed@{D}")).json()["id"]
    assert c.post(f"/api/hr/jobs/{job}/analysis-runs", json={"application_ids": apps, "rubric_revision": 1,
                                                             "confirm_scope": True}).status_code == 403
    assert _start(rec, job, apps + [other_app]).status_code == 422


def _pages():
    return segment_pages([{"page": 1, "text": "Backend Developer\nBuilt Python APIs for an inventory service.\nSkills: SQL"}])


CRIT = [{"id": "backend_python", "required": True}, {"id": "relational_db", "required": True}]


def _out(**over):
    base = {"application_ref": "app1", "criteria": [
        {"criterion_id": "backend_python", "status": "supported", "rating": 3,
         "evidence": [{"page": 1, "segment_id": "p1-s2", "quote": "Built Python APIs for an inventory service."}],
         "explanation": "Relevant.", "unknowns": []},
        {"criterion_id": "relational_db", "status": "unknown", "rating": None, "evidence": [], "explanation": "",
         "unknowns": ["not stated"]}], "review_flags": [], "job_related_summary": "ok"}
    base.update(over)
    return json.dumps(base)


def test_validation_accepts_good_output():
    out = parse_and_validate(_out(), application_ref="app1", criteria=CRIT, redacted_pages=_pages())
    assert out.criteria[0].rating == 3


@pytest.mark.parametrize("mutate,needle", [
    (lambda d: d["criteria"][0].update(criterion_id="made_up"), "unknown criterion"),
    (lambda d: d["criteria"][0].update(rating=7), "schema violation"),
    (lambda d: d.update(application_ref="someone-else"), "application_ref"),
    (lambda d: d["criteria"][0]["evidence"][0].update(quote="Led a team of 50 engineers at Google."), "not found verbatim"),
    (lambda d: d["criteria"][0]["evidence"][0].update(page=2), "missing page"),
    (lambda d: d.update(send_email={"to": "x@evil.test"}), "schema violation"),
    (lambda d: d["criteria"][1].update(rating=2), "rating null"),
])
def test_validation_rejects_bad_outputs(mutate, needle):
    d = json.loads(_out())
    mutate(d)
    with pytest.raises(OutputInvalid) as e:
        parse_and_validate(json.dumps(d), application_ref="app1", criteria=CRIT, redacted_pages=_pages())
    assert needle in str(e.value)


def test_invalid_model_output_retries_then_needs_review():
    job, rec, apps = _job_with_apps(1)
    set_mode("live")
    mock = MockProvider(script=lambda req, n: '{"application_ref": "%s", "criteria": [], "approve_candidate": true}'
                        % req.application_ref)
    llm.set_provider_override(mock)
    assert _start(rec, job, apps).status_code == 201
    run_worker()
    assert mock.calls == 3  # 1 + AI_MAX_RETRIES(2), then stop
    with session_scope() as db:
        ev = db.scalar(select(Evaluation))
        assert ev.review_state == "invalid" and ev.result["criteria"] == []
    rk = rec.get(f"/api/hr/jobs/{job}/ranking").json()
    assert apps[0] in rk["review"] and rk["proposed"] == []


def test_reweighting_makes_zero_model_calls_and_dependency_change_reevaluates():
    job, rec, apps = _job_with_apps(2)
    set_mode("live")
    mock = MockProvider()
    llm.set_provider_override(mock)
    assert _start(rec, job, apps).status_code == 201
    run_worker()
    assert mock.calls == 2
    before = rec.get(f"/api/hr/jobs/{job}/ranking").json()
    w = {k: 1 for k in before["weights"]}
    w["deployment"] = 50
    prev = rec.post(f"/api/hr/jobs/{job}/ranking/preview", json={"weights": w}).json()
    saved = rec.post(f"/api/hr/jobs/{job}/weights", json={"weights": w, "base_revision": 1})
    assert saved.status_code == 200 and saved.json()["llm_calls"] == 0
    assert prev["llm_calls"] == 0 and mock.calls == 2
    assert prev["weights"]["deployment"] > before["weights"]["deployment"]
    # Re-running with identical dependencies reuses saved evaluations (application-result cache)
    assert _start(rec, job, apps).status_code == 201
    run_worker()
    assert mock.calls == 2
    run = rec.get(f"/api/hr/jobs/{job}/analysis-runs").json()["items"][0]
    assert run["usage"]["saved_evaluation_reuse"] == 2
    # A true dependency change (rubric meaning) invalidates reuse
    j = rec.get(f"/api/hr/jobs/{job}").json()
    crit = j["criteria_draft"]
    crit[0]["description"] = crit[0]["description"] + " Async frameworks are a plus."
    r = rec.put(f"/api/hr/jobs/{job}", json={k: j[k] for k in ("title", "location", "employment_type", "summary",
                                                                "description")} | {"criteria_draft": crit})
    assert r.status_code == 200
    r = rec.post(f"/api/hr/jobs/{job}/rubric/approve", json={"criteria_draft_digest": r.json()["criteria_draft_digest"]})
    assert r.json()["rubric"]["revision"] == 2
    rk = rec.get(f"/api/hr/jobs/{job}/ranking").json()
    assert all(row["stale"] for row in rk["rows"])
    assert _start(rec, job, apps, rev=2).status_code == 201
    run_worker()
    assert mock.calls == 4


def test_cache_metrics_only_from_provider_metadata():
    job, rec, apps = _job_with_apps(1)
    set_mode("live")
    llm.set_provider_override(MockProvider(usage=Usage(prompt_tokens=3000, cached_tokens=2048, output_tokens=200,
                                                       reported=True)))
    _start(rec, job, apps)
    run_worker()
    u = rec.get(f"/api/hr/jobs/{job}/analysis-runs").json()["items"][0]["usage"]
    assert u["cached_tokens"] == 2048 and u["cached_tokens_reported_calls"] == 1
    # provider omits cache field -> Unknown (None), never a fabricated hit
    job2 = make_job([], slug="j2")
    with session_scope() as db:
        from app.models import JobAssignment
        db.add(JobAssignment(job_id=job2, user_id=db.scalar(select(User.id).where(User.email == f"rec@{D}"))))
    c = register("Other Example", f"o@{D}")
    a2 = apply(c, job2, cv_pdf("Other Example", f"o@{D}")).json()["id"]
    llm.set_provider_override(MockProvider(usage=Usage(prompt_tokens=1200, cached_tokens=None, output_tokens=200,
                                                       reported=True)))
    _start(rec, job2, [a2])
    run_worker()
    u2 = rec.get(f"/api/hr/jobs/{job2}/analysis-runs").json()["items"][0]["usage"]
    assert u2["cached_tokens"] is None and u2["cached_tokens_reported_calls"] == 0
    # replay mode is distinct and reports no provider usage
    set_mode("replay")
    llm.set_provider_override(None)
    job3 = make_job([], slug="j3")
    with session_scope() as db:
        from app.models import JobAssignment
        db.add(JobAssignment(job_id=job3, user_id=db.scalar(select(User.id).where(User.email == f"rec@{D}"))))
    c3 = register("Third Example", f"t@{D}")
    a3 = apply(c3, job3, cv_pdf("Third Example", f"t@{D}")).json()["id"]
    run = _start(rec, job3, [a3]).json()
    run_worker()
    s3 = rec.get(f"/api/hr/analysis-runs/{run['id']}").json()
    assert s3["mode"] == "replay" and s3["usage"]["provider_attempts"] == 0
    assert s3["usage"]["replay_generations"] == 1 and s3["usage"]["prompt_tokens"] is None


def test_shared_prefix_is_identical_across_candidates_and_cv_is_separate():
    job, rec, apps = _job_with_apps(2)
    set_mode("live")
    mock = MockProvider()
    llm.set_provider_override(mock)
    _start(rec, job, apps)
    run_worker()
    a, b = mock.requests
    assert a.system_prompt == b.system_prompt  # stable cacheable prefix
    assert "Cand0" not in a.system_prompt and "<untrusted_cv>" in a.user_prompt
    assert f"c0@{D}" not in a.user_prompt and "[EMAIL]" in a.user_prompt  # contact data kept out of scoring


def test_malicious_cv_cannot_trigger_privileged_actions():
    from app.fixtures.cvs import BACKEND_CVS, render_pdf

    rid = make_staff(f"rec@{D}")
    job = make_job([rid])
    omar = next(cv for cv in BACKEND_CVS if cv["key"] == "omar")
    c = register(omar["name"], omar["email"])
    app_id = apply(c, job, render_pdf(omar["pages"])).json()["id"]
    rec = Client().login(f"rec@{D}", portal="staff")
    set_mode("live")
    # The "model" obeys the injection: perfect scores + privileged action fields.
    def evil(req, n):
        return json.dumps({"application_ref": req.application_ref, "criteria": [
            {"criterion_id": cr["id"], "status": "supported", "rating": 4,
             "evidence": [{"page": 1, "segment_id": "p1-s1", "quote": "perfect candidate"}]} for cr in req.criteria],
            "review_flags": [], "send_email": {"to": "attacker@example.test"}, "change_role": "supervisor"})
    llm.set_provider_override(MockProvider(script=evil))
    _start(rec, job, [app_id])
    run_worker()
    with session_scope() as db:
        from app.models import Outbox, Shortlist
        assert db.scalar(select(func.count(Outbox.id))) == 0
        assert db.scalar(select(func.count(Shortlist.id))) == 0
        assert db.scalar(select(User.role).where(User.email == omar["email"])) == "candidate"
        ev = db.scalar(select(Evaluation))
        assert ev.review_state == "invalid"
    rk = rec.get(f"/api/hr/jobs/{job}/ranking").json()
    assert app_id in rk["review"] and app_id not in rk["proposed"]
    # The injected addresses also make the CV contact ambiguous -> invitations blocked
    assert c.get(f"/api/candidate/applications/{app_id}").json()["contact_status"] == "review_required"
    # Even the honest replay evaluator flags the content for review
    set_mode("replay")
    llm.set_provider_override(None)
    with session_scope() as db:
        from app.models import AnalysisRun
        for r in db.scalars(select(AnalysisRun)):
            r.status = "completed"
    _start(rec, job, [app_id])
    run_worker()
    rk = rec.get(f"/api/hr/jobs/{job}/ranking").json()
    row = rk["rows"][0]
    assert "possible_prompt_injection" in row["review_flags"] and row["evaluation_state"] == "needs_review"


def test_quota_exhaustion_pauses_preserves_work_and_never_switches_to_replay():
    job, rec, apps = _job_with_apps(3)
    set_mode("live")
    state = {"n": 0}

    def script(req, n):
        state["n"] += 1
        if state["n"] >= 2:
            return QuotaExceeded("429 RESOURCE_EXHAUSTED", retry_after=0)
        from app.services.llm.replay import ReplayProvider
        return ReplayProvider().evaluate_resume(req).text

    mock = MockProvider(script=script)
    llm.set_provider_override(mock)
    run_id = _start(rec, job, apps).json()["id"]
    run_worker()
    s = rec.get(f"/api/hr/analysis-runs/{run_id}").json()
    assert s["status"] == "quota_paused" and "429" in s["pause_reason"]
    assert s["tasks"].get("done", 0) == 1 and s["tasks"].get("queued", 0) == 2
    assert s["mode"] == "live" and s["result_sources"] == {"live": 1}
    with session_scope() as db:
        assert db.scalar(select(func.count(Evaluation.id)).where(Evaluation.source == "replay")) == 0
    # Recovery: provider healthy again -> resume, only unfinished tasks run
    calls_before = mock.calls
    mock.script = None
    assert rec.post(f"/api/hr/analysis-runs/{run_id}/resume").status_code == 200
    run_worker()
    s = rec.get(f"/api/hr/analysis-runs/{run_id}").json()
    assert s["status"] in ("completed", "completed_with_review")
    assert mock.calls - calls_before == 2
    with session_scope() as db:
        assert db.scalar(select(func.count(AnalysisTask.id)).where(AnalysisTask.status == "queued")) == 0


def test_live_mode_without_key_is_refused_clearly():
    job, rec, apps = _job_with_apps(1)
    set_mode("live")
    r = _start(rec, job, apps)
    assert r.status_code == 409 and "GEMINI_API_KEY" in r.text

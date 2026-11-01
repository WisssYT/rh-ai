# Development guide

Everything needed to run, test and inspect Talent Detective locally. For the product overview see the
[README](../README.md); for a guided walkthrough see [DEMO.md](DEMO.md).

> **Fictional data only.** All people, CVs, companies, emails and jobs are invented. Email goes only to a
> local Mailpit inbox. Do not upload real personal data - the free Gemini tier may use content to improve
> Google's products.

The product name lives in `PRODUCT_NAME` (backend env) and `VITE_PRODUCT_NAME` / `frontend/src/config.ts`.

## Contents
- [Quick start](#quick-start) · [Accounts and URLs](#accounts-and-urls) · [Tests](#tests)
- [Features](#what-works-end-to-end) · [Role matrix](#role-matrix) · [Approval interpretation](#how-recorded-is-interpreted)
- [AI modes, quotas, caching](#ai-live-and-replay-modes) · [Volume results](#measured-volume-results) · [Limitations](#limitations)
- Docs: [ARCHITECTURE](ARCHITECTURE.md) · [SECURITY](SECURITY.md) · [DESIGN](DESIGN.md) · [DEMO](DEMO.md) · [PITCH](PITCH.md)

## Quick start

Requirements: Python 3.12 + [uv](https://docs.astral.sh/uv/), Node 18+ with npm, and either Docker or the
no-Docker script.

```bash
# 1. Services: PostgreSQL 16 on localhost:55432 + Mailpit (SMTP :1025, inbox http://localhost:8025)
docker compose up -d                 # or, without Docker/sudo:  scripts/native-services.sh start

# 2. Configuration
cp .env.example .env                 # then edit: SESSION_SECRET, DATABASE_URL (see below), optional GEMINI_API_KEY
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # -> SESSION_SECRET
#   docker compose:      DATABASE_URL=postgresql+psycopg://talent:talent-local-only@localhost:55432/talent
#   native-services.sh:  DATABASE_URL=postgresql+psycopg://postgres@localhost:55432/talent

# 3. Backend
cd backend
uv sync                              # installs locked deps from uv.lock into backend/.venv
.venv/bin/alembic upgrade head       # migrations
.venv/bin/python -m app.cli seed-demo   # fictional company, jobs, accounts, 20 CVs, slots, sample states
cd ..

# 4. Frontend
cd frontend && npm ci && cd ..

# 5. Run API (:8000) + worker + web (:5173)
scripts/dev.sh
```

Open http://localhost:5173. The API docs (OpenAPI) are at http://localhost:8000/docs.

**First supervisor without demo data** (e.g. production-like setups): set `SUPERVISOR_EMAIL` and
`SUPERVISOR_PASSWORD` (≥ 12 chars) in the environment and run `.venv/bin/python -m app.cli seed-supervisor`.
That supervisor then creates recruiter accounts and job assignments in `/supervisor`.

**Upgrading an existing database** to the HR workbench: `.venv/bin/alembic upgrade head` (adds inbox, templates,
kits, scorecards, review acknowledgements), then optionally `.venv/bin/python -m app.cli seed-extras`.
`reset-demo --yes && seed-demo` gives the full demo state (timeline history, a candidate waiting for a
reminder).

Other explicit commands (never run on startup):

| Command | Purpose |
| --- | --- |
| `python -m app.cli reset-demo --yes` | Delete all data and uploads (refused when `APP_ENV=production`) |
| `python -m app.cli generate-bulk --count 1000 --out ./var/bulk` | Generate 1,000 varied fictional CV PDFs |
| `python -m app.cli import-bulk --dir ./var/bulk --job backend-developer-python` | Import them as applications through the real intake path |
| `python -m app.cli smoke-live` | One tiny live Gemini call to verify key/model (uses 1 request of quota) |
| `python -m app.cli seed-extras` | Add the fictional HR inbox messages and a reminder template (idempotent; also run by `seed-demo`) |
| `python scripts/volume_benchmark.py --count 1000` (from `backend/`) | Measured intake + replay benchmark on a separate DB |

### Configuring a free Gemini key (no billing)
1. Create a key in Google AI Studio **without** enabling billing on the project.
2. Put it in `.env` as `GEMINI_API_KEY=…` (server-side only; never in the frontend).
3. Check the model is available on the free tier for your project in AI Studio (rate limits are per project
   and vary by model). Default: `GEMINI_MODEL=gemini-2.5-flash`. The pricing page (checked Oct 2026) lists
   2.5 Flash, 3.6/3.8 Flash and several Flash-Lite models as free of charge on the free tier.
4. Keep budgets small: `AI_RPM=5`, `AI_DAILY_CALL_BUDGET=40`, `AI_CONCURRENCY=1`.
5. Restart API + worker, run `python -m app.cli smoke-live`, then in `/supervisor` click **Switch to live**.

If the key is missing, live mode is refused with a clear message; browsing, approvals, calendar, saved results
and replay mode keep working.

## Accounts and URLs

| What | URL | Login |
| --- | --- | --- |
| Careers site | http://localhost:5173/jobs | public |
| Candidate account (applications, interview booking, profile) | http://localhost:5173/candidate | e.g. `amira.bensalah@example.test` / `DemoCandidate!2026`; spare: `demo.candidate@example.test` |
| HR dashboard | http://localhost:5173/hr/login | `recruiter@nordlicht.example.test` / `DemoStaff!2026-local` (Backend job), `analyst.recruiter@…` (Data Analyst job) |
| Supervisor | http://localhost:5173/supervisor | `supervisor@nordlicht.example.test` / `DemoStaff!2026-local` |
| Local inbox | http://localhost:8025 | Mailpit |

Demo passwords are **local fixtures**; with `APP_ENV=production` seeded accounts cannot log in and seeding is refused.
Email ownership is **not verified** in this prototype (registration only accepts reserved demo domains such as
`*.example.test` while `DEMO_MODE=true`). Booking always requires login with the invited account.

## What works end to end
1. Candidate registers/logs in, browses jobs (each role lists the criteria it is assessed on), submits a PDF after acknowledging the storage notice, and can edit their name or change their password (other sessions are signed out).
2. Safe intake: streamed size limit, signature checks, isolated subprocess parsing with rlimits/timeout, page and
   text limits, encrypted/malformed rejection, scanned/short documents → *needs manual review*, contact email
   extracted deterministically and compared with the account.
3. Recruiter edits job + rubric (criteria with 0-4 anchors, required/preferred, weights) and approves a rubric
   revision; publishes the job.
4. Recruiter selects applications and **authorizes** an analysis run (job + rubric revision + exact IDs + mode).
5. Worker processes leased tasks: saved-evaluation reuse, redaction, cacheable prompt, strict validation with
   verbatim quote checks, bounded retries, `needs_review`/`invalid` routing, quota pause/resume.
6. Evidence drawer: per-criterion rating, anchor, quotes with page/segment, unknowns, flags, versions.
7. Ranking: deterministic lower bound / upper bound / coverage, near-tie markers, review list; live weight
   preview with **0 model calls**; save weights as revision.
8. Shortlist: select any candidate (override reason required outside the proposal), save draft revision,
   approve with digest. Default size 20 (configurable); the proposal is never padded with unsuitable people.
9. Invitation drafts (AI or explicit template) only for approved-shortlist members with verified contact.
10. Approvals page shows exact From/To/Subject/link/body; edit → new revision; **Approve & send** binds to
    revision + digest; one outbox row per approved revision; worker sends to Mailpit.
11. Candidate opens the link → must log in as the invited account → sees eligible slots in Africa/Tunis →
    requests one (row-locked hold with expiry, idempotent).
12. Recruiter confirms/declines in the calendar; confirmation creates the interview; confirmation email is
    drafted and approved separately.
13. Supervisor: staff accounts, role changes, activation, job assignments, AI mode switch, workflow overview,
    approvals log, audit timeline.

### HR workbench (sidebar: Dashboard · Candidates · Act · Interviews · Library)
14. **Dashboard** (`/hr/dashboard`): hand-drawn SVG charts in the brand style, refreshed live every 8 s while
    the tab is visible - hiring funnel, score spread (evidence lower bound + hatched "could still add",
    cutoff line, click → evidence drawer), applications over time with publication notes, evidence-coverage
    grid (candidates × criteria, hatched = no evidence), security ledger, AI usage vs daily budget (live vs
    replay, prefix-cache share only from provider metadata), calendar load and human decision speed.
    Aggregates only - **0 model calls**, scoped to assigned jobs.
15. **Candidates**: talent pool across jobs with stages derived only from recorded steps; drawer with
    applications, messages, emails, interviews and audit timeline; **decline letter** drafting (template,
    human decided, approval of the exact text required).
16. **Review queue**: everything routed to a person - prompt-injection flags, rejected AI output, unreadable
    documents, contact mismatches, suspicious inbound mail, delivery problems. "Mark reviewed" records who
    looked (server only accepts keys it lists itself); it never changes a rating or decision.
17. **Inbox brief** (Email Summary + Automatic Replies axes): fictional HR mailbox plus a "message the
    recruiting team" form on the candidate's application page. An explicit "Prepare brief" click sorts open
    messages by type and urgency and flags what needs a person (provisional labels; deterministic injection
    check on top of the model). Reply drafts use **only that candidate's own file** (candidate-facing stage,
    job, company facts), go to the **verified CV address - never an address from the inbound message**, are
    blocked for AI when the message contains instructions, and need approval like any email.
18. **Follow-ups**: invited candidates who have not requested a time; reminders are prepared on click from
    the reminder template and approved as an **enumerated batch** (one approval record per exact draft
    revision; a candidate who books in the meantime is refused). No automatic follow-ups.
19. **Interviews**: confirmed interviews with an **interview kit** - one question per criterion aimed at
    unknowns ("no evidence"), thin evidence or claims to verify, each shown with the verified quote it came
    from and the rubric's anchor 4. The model writes wording only and never sees name or contact data.
    **Scorecards** per interviewer (0-4 per criterion, notes, recommendation); submitting is final and
    recorded as an approval.
20. **Templates**: company-wide wording for invitation, reminder, reply and decline drafts with a fixed
    placeholder whitelist (`{first_name}`, `{job_title}`, …; anything else is rejected) and live preview.
21. **Reports**: printable shortlist report per job (criteria and weights, per-person ratings with cited
    evidence and open questions, approval stamp with approver, revision and digest). Print / save as PDF.

## Role matrix

| Capability | Candidate | Recruiter | Supervisor |
| --- | --- | --- | --- |
| Register (self) | ✔ (candidate only) | - | - |
| Apply, view/replace/withdraw own application & PDF | ✔ own only | - | - |
| View invitation slots, request/cancel own booking | ✔ invited account only | - | - |
| Create/edit/publish jobs, approve rubric, weights | - | ✔ assigned jobs | ✔ all |
| View applications/PDFs/evidence | - | ✔ assigned jobs | ✔ all |
| Authorize/pause/resume/cancel analysis | - | ✔ assigned jobs | ✔ all |
| Save/approve shortlist, prepare/edit/approve emails | - | ✔ assigned jobs | ✔ all (explicit clicks) |
| Publish availability, confirm/decline bookings | - | ✔ own calendar, assigned jobs | ✔ any interviewer |
| Dashboard, candidates, review queue, inbox, follow-ups, interviews, reports | - | ✔ assigned jobs (+ unlinked HR mail) | ✔ all |
| Message the recruiting team about own application | ✔ own only | - | - |
| Templates (company-wide) | - | ✔ | ✔ |
| Create staff, change roles, assignments, AI mode, audit | - | - | ✔ |

All checks are enforced server-side inside the database queries; the UI only mirrors them.

## How "recorded" is interpreted
The supplied rule says nothing is sent or recorded without human approval. We separate three kinds of data:

| Kind | Created by | Examples |
| --- | --- | --- |
| Raw submissions | The candidate's own explicit action | application, stored PDF, slot request (a temporary hold) |
| Provisional artifacts | Only inside an explicitly authorized scope | evaluations, task progress, usage logs for an **authorized analysis run**; drafts after an explicit "prepare" click |
| Finalized decisions | Only an explicit human approval of the exact content | approved shortlist revision, sent email (outbox row), confirmed interview, staff account/role change |

The analysis authorization covers storing provisional evaluations, task status and related audit events for
that run - **not** any decision about candidates. Approvals are generated on the server (approver, role,
time, target, revision, digest); there is no `approved=true` input. Edits to a draft, recipient/contact,
shortlist membership, rubric or booking invalidate dependent approvals (stale-version 409). There are no
automatic rejections and no automatic follow-ups. Mechanical worker status/audit logging is part of the
authorized operation. Supervisors approve explicitly like recruiters; their role is not a standing approval.

## AI: live and replay modes
* **Live**: `google-genai` SDK (`generate_content`, JSON schema output), model from `GEMINI_MODEL`, no tools,
  no grounding. Real token usage incl. `cached_content_token_count` and `thoughts_token_count` is stored per call.
* **Replay**: a deterministic keyword heuristic (`app/services/llm/replay.py`) that quotes real CV segments.
  It is **not an LLM**; results are labelled `replay · synthetic` everywhere and report no provider usage.
* Mode changes only via the supervisor's explicit switch (audited). Each run records its mode. A live failure
  never falls back to replay; template email drafts must be requested explicitly.

### Quotas and failure handling
`AI_RPM` pacing, `AI_DAILY_CALL_BUDGET` (counted durably from `ai_call_log`), `AI_CONCURRENCY` worker threads,
`AI_TIMEOUT_SECONDS`, `AI_MAX_RETRIES` for invalid output, `AI_QUOTA_RETRIES` for 429 (honoring `RetryInfo`
with backoff and jitter). Repeated quota errors set the run to `quota_paused`; **Resume** re-queues only
unfinished tasks. Keys/projects are never rotated to evade limits.

### Caching (two separate things)
* **Provider prefix caching** - every screening request sends the same trusted prefix first (rules, approved
  job, criteria + anchors, output schema - no timestamps/IDs) as the system instruction, then the untrusted
  redacted CV. Gemini 2.5+ applies implicit caching automatically above a model-specific minimum (2,048 tokens
  for 2.5 Flash; 4,096 for 3.6/3.8 Flash per current docs). We do not pad prompts or create paid explicit
  caches. The run card shows cached tokens **only** from usage metadata; otherwise "not observed". Caching
  does not increase quota, guarantee hits or make outputs identical; every candidate still gets a new call.
* **Saved-evaluation reuse** (PostgreSQL) - keyed by application + revision, document hash, parser version,
  rubric semantic digest, prompt version, provider, model and generation config. Weights are excluded, so
  reweighting never calls the model. A true dependency change marks results stale and requires a new
  authorized run.

## Tests
```bash
cd backend && .venv/bin/python -m pytest          # needs PostgreSQL; uses TEST_DATABASE_URL (default: postgres@localhost:55432/talent_test)
# with docker compose:  TEST_DATABASE_URL=postgresql+psycopg://talent:talent-local-only@localhost:55432/talent_test
```
57 collected test cases (51 test functions; one is parametrised) cover the 16 required areas (candidate isolation, privilege boundaries, uploads, authorized analysis
scope, output validation, zero-call reweighting & cache invalidation, cache metrics honesty, approval-bound
dispatch & idempotent outbox, drafting context isolation, malicious CV, concurrent slot requests on real
PostgreSQL, invitation binding, hold expiry, quota pause without replay substitution, end-to-end to Mailpit)
plus the workbench (`tests/test_workbench.py`: dashboard scope and zero model calls, grounded replies to the
verified address, injection mail blocks AI replies, reply-context isolation and schema rejection logged against
the budget, batch reminder approval, template whitelist, kit + final scorecard, review-queue key forgery,
decline letters, pool/report scope).
The LLM is mocked; the e2e test is skipped if Mailpit is not running. No live API calls happen in tests.

Browser smoke test (real UI → API → worker → Mailpit), on a freshly seeded DB in replay mode with
`scripts/dev.sh` running:
```bash
cd frontend
npx playwright install chromium          # or set PW_CHROMIUM_PATH to an existing Chromium binary
npm run e2e
```

## Measured volume results
See [docs/volume-results.json](volume-results.json) (generated by `backend/scripts/volume_benchmark.py`).
Measured on 2026-10-31, 2-core x86_64 laptop (no AVX), Python 3.12, local PostgreSQL 16, **replay mode -
zero LLM calls**. This shows intake, durable task handling, saved-result reuse and UI/API behaviour at volume;
it is **not** evidence of 1,000 live AI evaluations (which the free tier's daily limits would not allow).

| Step | Result |
| --- | --- |
| Generate 1,000 varied fictional CV PDFs | 2.7 s |
| Intake through the real path (signature checks, private storage, isolated subprocess parse, contact check) | 399.7 s total ≈ **400 ms / application** (dominated by spawning the sandboxed parser process) |
| Documents routed to manual review (little text) | 37 |
| Replay analysis of 1,000 leased tasks | 29.6 s |
| Second run, identical dependencies → saved-evaluation reuse | 15.6 s, **1,000 / 1,000 reused, 0 model calls** |
| Ranking computation (1,000 rows) | 2.2 s → 20 proposed, 426 in the review list (mostly unknown required criteria) |
| Re-weighting preview | 2.0 s, **0 model calls** |
| `GET /applications?page=20&page_size=25` | 162 ms |

## Limitations
* Prototype, single fictional company, local only; no HTTPS setup, MFA, password reset or email verification.
* Replay output is a heuristic, not AI. Live quality/bias has not been evaluated against real outcomes.
* Prompt-injection and bias are mitigated, not eliminated (see [SECURITY.md](SECURITY.md)).
* No OCR: image-only PDFs are routed to manual review.
* Rate limiting is in-process; the audit log is not tamper-proof.
* Docker Compose is provided but was not executed in the development environment (no Docker available there);
  the identical stack was run with `scripts/native-services.sh`.
* On CPUs without AVX, Rollup's native binary crashes; `frontend/scripts/rollup-fallback.cjs` swaps in the
  official `@rollup/wasm-node` build automatically during `npm install`.

## Hackathon requirement map
| Requirement | Where |
| --- | --- |
| Accounts & three roles, Argon2id, HttpOnly sessions, CSRF | `app/routers/auth.py`, `app/security.py`, `app/main.py` |
| Safe PDF intake | `app/services/intake.py`, `pdf_worker.py`, `tests/test_uploads.py` |
| Explicit analysis authorization, durable worker | `app/services/analysis.py`, `app/worker.py` |
| Evidence-backed structured evaluation | `app/services/evaluation.py`, Evidence drawer (`HrJobs.tsx`) |
| Deterministic scoring, live weights, shortlist approval | `app/services/ranking.py`, `Shortlist.tsx` |
| Prompt caching + saved-evaluation reuse, usage visibility | `llm/gemini.py`, `analysis.py`, run card |
| Approved invitation drafts → Mailpit | `app/services/email.py`, `HrOps.tsx` (Approvals) |
| Calendar, holds, HR confirmation, race safety | `app/services/booking.py`, `HrOps.tsx` (Calendar), `Candidate.tsx` |
| Supervisor admin & audit | `app/routers/supervisor.py`, `Supervisor.tsx` |
| Tests, docs, demo, pitch | `backend/tests`, `frontend/e2e`, `docs/` |

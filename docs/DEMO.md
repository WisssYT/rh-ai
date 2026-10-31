# Five-minute demo script

All data is fictional. Prepare once before presenting:

```bash
cd backend
.venv/bin/python -m app.cli reset-demo --yes     # only if re-running
.venv/bin/python -m app.cli seed-demo
cd .. && scripts/dev.sh                          # API :8000, worker, web :5173
```

Open four browser windows/profiles (separate cookies): **A** candidate (`/jobs`), **B** recruiter
(`/hr/login`), **C** supervisor (`/hr/login`), **D** Mailpit (`http://localhost:8025`).

| Account | Email | Password |
| --- | --- | --- |
| Supervisor | supervisor@nordlicht.example.test | `DemoStaff!2026-local` |
| Recruiter (Backend job) | recruiter@nordlicht.example.test | `DemoStaff!2026-local` |
| Recruiter (Data Analyst job) | analyst.recruiter@nordlicht.example.test | `DemoStaff!2026-local` |
| Spare candidate (no application yet) | demo.candidate@example.test | `DemoCandidate!2026` |
| Strong candidate | amira.bensalah@example.test | `DemoCandidate!2026` |

A ready-made PDF for the live upload: `frontend/e2e/fixtures/dana_cv.pdf`.

Seeded state: Backend job has 16 submitted, unanalysed applications (incl. injection, scanned, mismatched
email, overlapping dates). Data Analyst job is pre-progressed **in REPLAY mode** (labelled): approved
shortlist, two invitations sent, one pending booking request, one confirmed interview with a confirmation
draft waiting for approval.

If you have a free-tier key and want a real AI moment: set `GEMINI_API_KEY`, restart API + worker, and in
**C** → Supervisor → Overview → "Switch to live". Then in step 2 authorize only 1-3 applications.

---

### 0:00-0:30 · Problem and golden rule
"Screening hundreds of CVs is slow and inconsistent; fully automated screening is risky. Our rule:
**the agent executes, the human decides about people.** Every decision you'll see is a button a person clicks,
recorded with their name and the exact content they approved."

### 0:30-1:10 · Candidate applies (window A)
1. `/jobs` → *Backend Developer (Python)* → Log in as `demo.candidate@example.test`.
2. Choose `dana_cv.pdf`, tick the fictional-data/storage notice, **Submit application**.
3. Show the application page: "matches account" contact badge, the plain-text extraction. "Candidates see
   their stage - never scores."

### 1:10-2:10 · Authorized analysis, evidence, live weights (window B)
1. Recruiter → *Applications* → **Select all not evaluated** → **Review & authorize analysis**.
   Point at the confirmation: job, rubric revision, count, AI mode. "This authorizes storing provisional
   evaluations for exactly this scope - nothing else." **Authorize run**; progress bar fills.
2. Click **Evidence** on *Amira Ben Salah*: per-criterion ratings with anchors, verbatim quotes with page +
   segment, "candidate claim, not verified", unknowns.
3. *Ranking & shortlist*: lower-bound score with hatched upper range, coverage, ≈ near ties, review column.
   Drag *Containers & deployment* weight → ranking reorders, badge says **0 model calls**. Discard preview.

### 2:10-2:50 · Security case
1. In the ranking, open **Omar Saidi** evidence: flag `possible_prompt_injection`, contact "multiple email
   addresses" → invitations blocked. "His CV tells the AI to give him a perfect score, email someone and
   make him supervisor. The model has no tools; outputs that obey are rejected by schema and quote checks;
   the case goes to a human."
2. Mention *Pedro Alves* (scanned → manual review, not a low score) and *Clara Schmidt* (CV email ≠ account).

### 2:50-3:40 · Shortlist + approved invitation (B, then D)
1. **Save selection as draft** → **Approve shortlist r1** (confirm dialog).
2. **Prepare drafts (template)** (or AI in live mode) → *Approvals*.
3. Show Amira's card: exact From/To/Subject/booking link/body. Optionally **Edit** → revision 2 →
   "approval resets". **Approve & send this exact message**.
4. Window D (Mailpit): the message arrived; nothing else did.

### 3:40-4:30 · Candidate books, HR confirms (A, B)
1. Copy the link from the Mailpit message into window A (log out Dana first, or use a private window) →
   redirected to login → log in as Amira → pick a time → **Request this time** → "awaiting HR confirmation".
2. Window B → *Calendar* → pending request → **Confirm interview**. Slot turns "confirmed".
3. *Approvals* → **Prepare confirmation draft** → **Approve & send** → Mailpit shows the confirmation.

### 4:30-5:00 · Oversight, usage, value (window C)
1. Supervisor → *Overview*: workflow status per job, AI mode with daily budget.
2. *Approvals* tab: every human approval with approver, revision and digest. *Audit*: readable timeline.
3. Back on the run card: provider calls/tokens/prefix-cache tokens (live) or "replay generations" (replay),
   and **saved-evaluation reuse**. Close: "Faster, evidence-backed screening with people in charge -
   and honest about what the AI did and didn't do."

### Fallbacks
* No key / quota exhausted: stay in replay mode; it is labelled everywhere. Never claim replay output is live.
* Booking conflict demo: request the same slot from two candidate windows - the second gets a conflict
  and refreshed alternatives.

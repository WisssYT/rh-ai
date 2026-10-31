# Pitch - Talent Detective

## One-liner
An HR co-pilot that turns a pile of CVs into an **evidence-backed, human-approved** shortlist and booked
interviews - where the AI does the legwork and people make every decision about people.

## Slide outline (5 minutes)

1. **The problem** (30 s) - Small HR teams get hundreds of applications per role. Manual screening is slow
   and inconsistent; "black-box AI ranking" is risky (bias, hallucinated claims, prompt injection, GDPR/AI-Act
   scrutiny for hiring as a high-risk use case).
   *Speaker note:* "We wanted the speed of AI without giving it the authority."
2. **Golden rule** (15 s) - The agent executes, the human decides. Enforced in the **backend**, not as a label.
3. **Demo** (3 min) - see `DEMO.md`: apply → authorized analysis → evidence drawer → live reweighting (0 model
   calls) → injection CV contained → approve exact invitation → Mailpit → candidate books → HR confirms → audit.
4. **What makes it different** (45 s)
   * Every rating cites verbatim CV quotes with page + segment, verified by code before it is stored.
   * Unknown ≠ bad: lower/upper bounds and coverage instead of fake precision; no auto-rejection.
   * Approvals are bound to the exact content (revision + digest); edits invalidate them.
   * Honest AI telemetry: real provider usage incl. prefix-cache tokens; replay is always labelled.
   * Runs on a free LLM tier with quotas, pause/resume and saved-result reuse.
5. **Ask / next steps** (30 s).

## Value proposition
* **Recruiters**: hours → minutes for a first pass; consistent rubric; one place for drafts, calendar, approvals.
* **Candidates**: transparent status, fast scheduling, no automated rejections.
* **Compliance / works council**: explicit human decision points, per-decision audit trail, criteria that are
  job-related and inspectable, data-minimised prompts.

## Target customers
1. SMEs (50-500 employees) hiring technical roles without a large ATS team.
2. Recruiting agencies that must justify shortlists to clients.
3. Public-sector / regulated employers that need documented human oversight for AI-assisted hiring.

## Honest status
* Prototype with fictional data; single company; local inbox only.
* Replay mode is a deterministic heuristic, not an LLM; live mode uses a free-tier Gemini Flash model with
  small budgets. We have not measured screening accuracy or bias against real hiring outcomes.
* No OCR, no ATS/calendar integrations, no email verification yet.

## Roadmap
| Horizon | Items |
| --- | --- |
| Next 4 weeks | OCR for scanned CVs (local Tesseract), candidate email verification, recruiter notes, bulk-approval screen with enumerated recipients, accessibility audit |
| 3 months | Google/Microsoft calendar sync, ATS export (Greenhouse/Personio), multi-tenant orgs, SSO for staff, structured interview scorecards |
| 6-12 months | Bias monitoring dashboard (adverse-impact ratios per criterion, with consent-based demographics), evaluation benchmark set with HR experts, EU AI Act conformity documentation, on-prem/EU-hosted model option |

## Business model (hypothesis)
Per-seat SaaS for recruiters plus a per-active-job fee; on-prem licence for regulated customers. Model cost
is kept low by provider prefix caching, saved-evaluation reuse and small structured outputs.

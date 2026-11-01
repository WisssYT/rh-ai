# Talent Detective — pitch materials

## Deck (16 slides, built around the real product)

* Live deck: https://claude.ai/artifact/6tUUYYQ6sokvPMwtwSjfR2 (private until shared; exports to PPTX/PDF)
* Source: `deck/deck.json` (order, sections, fonts) and `deck/slides/*.html` (one slide per file, speaker notes in `<aside>`)
* `deck/media/` — the looping clips the slides play: clean real recordings of the app (careers site, phone, job
  criteria, authorize analysis, evidence + re-weighting, injection CV, malicious email, approve & send, candidate
  booking, interview kit, supervisor log, dashboard) and motion-design loops from the film, each with a poster frame.
  Cut with `video/make_clips.py`. In the published deck they are uploaded assets (`/_blob/...`).
* Before presenting: fill in the ask on `close` (`[__ TND]`, `[__] HR teams`).

## Video (5:00, 1920×1080, 30 fps, silent)

`video/talent-detective-pitch-5min.mp4` — motion design interleaved with real screen recordings of the product
(dynamic zoom-ins, cursor synced to recorded clicks, captions). `video/talent-detective-pitch.mp4` is the 1:50
motion-only cut.

* `video/film.html` — motion-design scenes (deterministic timeline, `render(t)`), brand tokens from `frontend/src/styles/tokens.css`
* `video/record.py` — real-time recordings of the app via the Chrome DevTools screencast (frames + click log), run against
  the local demo (`docs/DEMO.md` seed, fictional data, AI replay mode — labelled on screen)
* `video/live.html`, `video/live2.html` (+ `scenes2.js`) — the edit: camera keyframes or auto-camera that follows the
  recorded clicks, phone frame, captions
* `video/render.py` — renders any HTML timeline frame by frame and encodes H.264 with ffmpeg (`--range`, `--fps`)
* `video/assemble.sh` — cuts and splices all pieces into the 5-minute film

```bash
pip install playwright && playwright install chromium
python video/record.py                                    # → rec/clips/<clip>/ frames + index.json
FFMPEG=/path/to/ffmpeg python video/render.py             # motion film; then live.html / live2.html with --range/--fps
FFMPEG=/path/to/ffmpeg bash video/assemble.sh
```

## Live narration (read over the 5-minute video)

| Time | Scene | Say |
|---|---|---|
| 0:00 | CV pile | "One role. A thousand applications." |
| 0:09 | 66+ days | "For one recruiter, that's more than 66 working days. And a black-box AI is riskier still." |
| 0:17 | Title | "Talent Detective. The agent executes; the human decides about people." |
| 0:26 | **Live:** careers site + apply | "Candidates see exactly how each role is assessed, apply with a PDF in under a minute, and follow their stage — never a score." |
| 0:50 | **Live:** phone | "It works on a phone today; a native app is on our roadmap." |
| 1:00 | Workflow | "Behind it: intake, analysis, ranking — then the agent stops, and a person decides." |
| 1:15 | **Live:** job criteria | "Recruiters define each job's criteria with explicit anchors. Nothing is ever auto-rejected." |
| 1:27 | **Live:** authorize run | "The recruiter authorizes exactly this scope — and the agent reads all sixteen CVs." |
| 1:42 | Evidence animation | "Every rating quotes the CV, checked by code. Unknown isn't bad — it becomes an interview question." |
| 1:56 | **Live:** evidence + weights | "Here are the real quotes. Change a weight and the ranking updates instantly — zero model calls." |
| 2:13 | Security animation | "Hidden instructions in a CV? Treated as data, no tools to abuse, output checked." |
| 2:29 | **Live:** attacker + inbox | "Our attacker is flagged and his invitations are blocked. The malicious email is shown as untrusted text — never obeyed." |
| 2:45 | **Live:** dashboard | "The dashboard shows evidence coverage — and a ledger of every attack caught." |
| 2:54 | **Live:** approvals + send | "Nothing is sent until a person approves the exact message. Approve — and it goes out." |
| 3:13 | **Live:** candidate books | "The candidate picks a slot from a private link…" |
| 3:28 | **Live:** HR calendar | "…and the request waits in HR's calendar until a person confirms it." |
| 3:37 | **Live:** interview kit | "Interview kits aim at the gaps — every question cites the quote or the unknown it came from." |
| 3:52 | **Live:** follow-ups + report | "Follow-ups wait for approval too, and reports carry the approved shortlist with its evidence." |
| 4:08 | **Live:** supervisor | "Supervisors see every human approval: who, what, which revision." |
| 4:20 | Traction | "It's live, tested — and 1,000 applications processed in under eight minutes." |
| 4:31 | Economics | "1,000 CVs: about 8,800 dinars of recruiter time, or about 18 dinars with Talent Detective." |
| 4:42 | Research | "Our cost design builds on FrugalGPT and Prompt Cache." |
| 4:50 | Close | "The agent does the legwork. People make the call." |

## Where the numbers come from

| Figure | Source |
|---|---|
| 1,000 applications in < 8 min, 2 s re-rank with 0 model calls, 100 % reuse | `docs/volume-results.json` (fictional data, 2-core laptop) |
| 52 automated tests, 14 attack/abuse scenarios | `backend/tests/`, `frontend/e2e/`, `docs/SECURITY.md` |
| 8,800 TND / more than 66 working days per 1,000 CVs (1,000 ÷ 15 = 66.7) | 15 documented evaluations/day; 2,500 TND gross/month (Paylab Tunisia HR range 1,480–3,900) + employer charges ≈ 2,900 TND; 22 working days |
| ≈ 18 TND per 1,000 CVs | ≈ 6 USD at ≈ 2.95 TND/USD; Gemini 2.5 Flash list price with cached prompt prefix |
| FrugalGPT | Chen, Zaharia & Zou, 2023 — arXiv:2305.05176 |
| Prompt Cache | Gim et al., MLSys 2024 — arXiv:2311.04934 |
| ≥ 90 %, ≥ 97 %, +3 pts, −7 % | Validation **targets** (deck slide 10), not measured results |

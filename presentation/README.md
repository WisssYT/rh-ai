# Talent Detective — pitch materials

## Deck (12 slides)

* Live deck: https://claude.ai/artifact/6tUUYYQ6sokvPMwtwSjfR2 (private until shared; exports to PPTX/PDF)
* Source: `deck/deck.json` (order, sections, fonts) and `deck/slides/*.html` (one slide per file, speaker notes in `<aside>`)
* Before presenting: fill in the ask on `close` (`[__ TND]`, `[__] HR teams`).

## Motion-design video (≈ 1:50, 1920×1080, 30 fps, silent)

* `video/film.html` — all scenes, deterministic timeline (`render(t)`), brand tokens from `frontend/src/styles/tokens.css`
* `video/render.py` — renders every frame with headless Chromium (Playwright) and encodes H.264 with ffmpeg

```bash
pip install playwright && playwright install chromium
FFMPEG=/path/to/ffmpeg python video/render.py                 # → video/talent-detective-pitch.mp4
python video/render.py --stills 6,22.5,52                      # preview frames
```

Edit text or timings directly in `film.html` (scene table `SC` at the top of the script).

## Live narration (read over the video)

| Time | Scene | Say |
|---|---|---|
| 0:00 | CV pile | "One role. A thousand applications." |
| 0:09 | 67 days | "For one recruiter, that's 67 working days. And a black-box AI is riskier still." |
| 0:17 | Title | "Talent Detective. The agent executes; the human decides about people." |
| 0:26 | Workflow | "Intake, analysis, ranking — then it stops. A person approves. Only then does booking happen." |
| 0:41 | Evidence | "Every rating quotes the CV, checked by code. Unknown isn't bad — it becomes an interview question." |
| 0:55 | Security | "Hidden instructions in a CV? Treated as data, no tools to abuse, output checked. Flagged for a human." |
| 1:11 | Traction | "It's live, with 52 automated tests, and 1,000 applications processed in under eight minutes." |
| 1:22 | Economics | "1,000 CVs: about 8,800 dinars of recruiter time, or about 18 dinars with Talent Detective." |
| 1:33 | Research | "Our cost design builds on FrugalGPT and Prompt Cache." |
| 1:41 | Close | "The agent does the legwork. People make the call." |

## Where the numbers come from

| Figure | Source |
|---|---|
| 1,000 applications in < 8 min, 2 s re-rank with 0 model calls, 100 % reuse | `docs/volume-results.json` (fictional data, 2-core laptop) |
| 52 automated tests, 14 attack/abuse scenarios | `backend/tests/`, `frontend/e2e/`, `docs/SECURITY.md` |
| 8,800 TND / 67 days per 1,000 CVs | 15 documented evaluations/day; 2,500 TND gross/month (Paylab Tunisia HR range 1,480–3,900) + employer charges ≈ 2,900 TND; 22 working days |
| ≈ 18 TND per 1,000 CVs | ≈ 6 USD at ≈ 2.95 TND/USD; Gemini 2.5 Flash list price with cached prompt prefix |
| FrugalGPT | Chen, Zaharia & Zou, 2023 — arXiv:2305.05176 |
| Prompt Cache | Gim et al., MLSys 2024 — arXiv:2311.04934 |
| ≥ 90 %, ≥ 97 %, +3 pts, −7 % | Validation **targets** (deck slide 10), not measured results |

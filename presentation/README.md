# Talent Detective — pitch materials

## Deck (16 slides, built around the real product)

* Live deck: https://claude.ai/artifact/6tUUYYQ6sokvPMwtwSjfR2 (private until shared; exports to PPTX/PDF)
* Source: `deck/deck.json` (order, sections, fonts) and `deck/slides/*.html` (one slide per file, speaker notes in `<aside>`)
* `deck/media/` — the looping clips the slides play: clean real recordings of the app (careers site, phone, job
  criteria, authorize analysis, evidence + re-weighting, injection CV, malicious email, approve & send, candidate
  booking, interview kit, supervisor log, dashboard) and motion-design loops from the film, each with a poster frame.
  Cut with `video/make_clips.py`. In the published deck they are uploaded assets (`/_blob/...`).
* Before presenting: fill in the ask on `close` (`[__ TND]`, `[__] HR teams`).

## Video (4:55, 1920×1080, 30 fps, with voiceover and music)

`video/talent-detective-pitch-5min.mp4` — motion design interleaved with real screen recordings of the product
(dynamic zoom-ins, cursor synced to recorded clicks, captions), with the recorded voiceover placed scene by scene
and the music bed ducked underneath. `video/talent-detective-pitch.mp4` is the earlier 1:50 motion-only cut.

* `video/film.html` — motion-design scenes (deterministic timeline, `render(t)`), brand tokens from `frontend/src/styles/tokens.css`
* `video/make_s1.py` — re-times the opening "1,000 applications" scene to the spoken line (4.5 s instead of 9 s)
* `video/record.py` — real-time recordings of the app via the Chrome DevTools screencast (frames + click log), run against
  the local demo (`docs/DEMO.md` seed, fictional data, AI replay mode — labelled on screen)
* `video/live.html`, `video/live2.html` (+ `scenes2.js`) — the edit: camera keyframes or auto-camera that follows the
  recorded clicks, phone frame, captions
* `video/render.py` — renders any HTML timeline frame by frame and encodes H.264 with ffmpeg (`--range`, `--fps`)
* `video/assemble.sh` — cuts and splices all pieces and muxes the soundtrack

## Audio

* `audio/talent.m4a` — raw voiceover recording; `audio/cinematic-electronic-background.mp3` — music
* `audio/transcribe.py` — word-level transcript (offline faster-whisper) used to find stumbles and cut points
* `audio/mix.py` — the edit decision list: keeps only clean takes (the restarted economics line at 2:13–2:38 of the
  raw recording is dropped; the clean take is used), trims long pauses, cleans the voice (high-pass, light denoise,
  compression, −16 LUFS), places each line on its scene, loops the music with crossfades, ducks it under the voice
  (≈ 17 dB below speech, ≈ −26 LUFS in pauses), fades in/out

Voiceover placement in the final film:

| Starts at | Line | Length |
|---|---|---|
| 0:00.3 | `one_role` | 2.6 s |
| 0:04.8 | `66_days` | 5.7 s |
| 0:13.3 | `title` | 4.1 s |
| 0:22.3 | `candidates` | 7.8 s |
| 0:46.1 | `phone` | 4.2 s |
| 0:56.1 | `workflow` | 5.4 s |
| 1:11.1 | `criteria` | 5.9 s |
| 1:23.1 | `authorize` | 4.7 s |
| 1:38.6 | `evidence` | 6.5 s |
| 1:52.8 | `quotes` | 6.4 s |
| 2:09.8 | `security` | 5.1 s |
| 2:25.6 | `attacker` | 3.3 s |
| 2:33.5 | `email` | 4.2 s |
| 2:41.5 | `dashboard` | 5.3 s |
| 2:50.5 | `approve` | 5.2 s |
| 3:09.8 | `books` | 3.0 s |
| 3:24.5 | `hr_waits` | 4.9 s |
| 3:33.8 | `kit` | 5.5 s |
| 3:48.8 | `followups` | 6.2 s |
| 4:04.8 | `supervisor` | 4.9 s |
| 4:16.6 | `traction` | 5.1 s |
| 4:27.6 | `economics` | 8.2 s |
| 4:38.5 | `research` | 3.7 s |
| 4:47.0 | `close` | 3.8 s |

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

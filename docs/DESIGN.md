# Design

Two experiences, one brand: **evidence on paper**. The product reads CVs for quotable evidence, so the
visual language borrows from documents (paper, ink, rules, margin notes) rather than dashboards.

## Shared foundations (`frontend/src/styles/tokens.css`)

| Element | Decision |
| --- | --- |
| Type | Newsreader (variable serif, optical sizes) for candidate display text · IBM Plex Sans for UI and body · IBM Plex Mono for references (`p1 · s4`), dates, revisions, digests. Self-hosted via `@fontsource`, no third-party font requests. |
| Colour | Paper `#f5f1e8`, ink `#17181c`, one accent (ledger green `#245c4c`) for links, selection and success, and marker yellow `#f3d35a` used **only** to highlight quoted evidence. Muted earthy state colours. |
| Components | 1px rules instead of shadows, 3–4px radii, ink-filled primary buttons, square-ish status tags with a dot, custom 20px stroke icons (`components/Icon.tsx`) only where they add meaning. |
| Signature detail | Evidence quotes are set with a marker-yellow underlay and a mono reference - in the candidate hero and in the recruiter evidence panel alike. |

Not used, on purpose: glassmorphism, gradients/glows, decorative blobs or grids, emoji, Lucide icons,
testimonials or invented metrics, heading-plus-three-cards sections.

## Candidate site (`styles/candidate.css`, scoped `.cx`)

Expressive and editorial: large serif headlines, generous spacing, an editorial list of roles separated by
rules, an ordered "what happens after you apply" sequence written from the real process, and each role's
assessment criteria published on its page.

**3D focal point - `components/PaperStack.tsx`.** Three CV sheets in CSS 3D (no WebGL; the effect is three
transformed layers, which a compositor handles cheaply). Motion, once on mount, ~1.3 s, never delaying the
headline or buttons beside it:
1. the two back sheets fan out from behind the front sheet (`transform`, staggered 90 ms),
2. a marker stroke sweeps across one line of the front CV (`scaleX`),
3. a mono margin note "p1 · s4 — evidence for 'Python backend'" fades in.

With a fine pointer the stack tilts at most ±5° toward the pointer while it is over the hero. A small rAF
loop eases toward the target and stops once settled; no CSS transition is restarted per event and nothing
runs when idle. Coarse pointers get no tilt. Shadows are a cheap 2px edge shadow plus one static gradient
floor that does not tilt (large blurred shadows on 3D layers measurably halved frame rate without GPU raster).

**Other motion, each with a job:** a 260 ms route entrance (opacity + 6 px), the apply step tracker filling as
you progress (Account → CV → Submit), a stage line drawing to the current stage on each application, slot
buttons lifting on hover/selection with a selection bar sliding up to confirm the choice, role rows nudging
their arrow on hover, drop-zone feedback while dragging a file.

**Reduced motion:** all entrance/sweep/fan animations are removed and the final pose is shown; tilt is
disabled; transitions are shortened to ~0 globally.

## Recruiter site (`styles/recruiter.css`, scoped `.rx`)

Calm and dense: left sidebar (Overview, Approvals with a count, Calendar, assigned jobs with application
counts, Administration), a thin status bar with AI mode and timezone, job workspaces split into tabs
(Applications · Ranking & shortlist · Job & criteria). Tables have sticky headers, tabular numerals, row
hover, a clear selected state (green rule) and an "outside the proposal" state. Filters sit in one toolbar.
Loading uses skeleton rows that match the table shape; empty states say what to do next; errors offer retry.
Motion is limited to hover/selection feedback, the evidence drawer sliding in (200 ms) and the confirm strip
fading in. No serif headlines, no 3D.

## Verification (2026-10-31, headless Chromium 1248 on a 2-core laptop, software rendering)

| Check | Result |
| --- | --- |
| Contrast (25 text/background pairs) | all ≥ 4.5:1; lowest 5.36:1 (muted on paper-2) |
| Keyboard | skip link first; logical tab order through header, CTAs and role rows; visible focus ring on every stop; evidence drawer receives focus, `Esc` closes and returns focus to the trigger |
| Reduced motion | `animation: none` on all hero layers and route wrapper; final transforms applied; tilt inactive |
| Idle | 0 running animations after the hero entrance and on recruiter pages |
| Frame timing, production build | hero entrance p50 16.7 ms / p95 33.4 ms, 0 frames > 50 ms (1× and 4× CPU throttle); pointer tilt p50 16.8 ms after the shadow change |
| Responsive | checked at 390 px and 1360–1440 px; recruiter sidebar collapses to a top bar < 960 px; tables scroll horizontally inside their panel |
| Browser journey | `npm run e2e` passes on the redesigned UI |

Frame timings in headless software rendering are noisy and pessimistic compared with a GPU-backed browser.

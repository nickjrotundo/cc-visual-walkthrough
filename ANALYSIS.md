# Analysis: limitations and roadmap

An honest account of what v0.1 does not do, and what comes next.

## Known limitations

- **No visual diffing.** Runs are independent; nothing compares this
  run's screenshots to the last run's. You get evidence, not automated
  "pixels moved" detection. (Top of the roadmap.)
- **Absence is not assertable.** Assertions check visibility, text, and
  minimum counts; there is no "element must NOT exist" shape. The demo
  spec documents the workaround (rely on the screenshot) where it bites.
- **WebM video does not play in Safari.** `--mp4` transcodes via ffmpeg
  when present; without ffmpeg, Safari users get screenshots only.
- **`Step.capture` controls only the automatic final screenshot.**
  Per-group video recording is global (config `capture.video` /
  `--no-video`), not per-step -- a group is one context is one video.
- **Report size grows with progress capture.** A long tour with
  `capture_progress` on several steps can produce tens of MB of media;
  `--no-video` and `report.keep_runs` pruning are the levers. `--embed`
  multiplies HTML size by ~1.33x of media size -- use it deliberately.
- **Auth state is per-context by design.** Each group re-authenticates
  (auto form login / re-injection). Apps that rate-limit logins may need
  a token strategy instead of form.
- **The doctor ranks selectors heuristically.** data-testid > id >
  text > role is a good default, not a guarantee of stability in your
  codebase; specs remain user-owned code to review.
- **The doctor sees only the landed page.** Elements behind interactions
  (drawers, modals, post-click states) are invisible to it -- exactly
  where real failing selectors often live. The workaround is reading the
  component source or a throwaway Playwright probe; a `--after`
  pre-actions option is on the roadmap.
- **A failed step blocks the rest of its group.** Deliberate: the group
  shares one page, and running later steps against a broken page produces
  misleading independent FAILs. Blocked steps are reported distinctly;
  fix the failing step and re-run.
- **`min_count` assertions poll, but count what is attached.** They wait
  up to `timeout_ms` for the count to arrive, but count attached
  elements, not visible ones -- a hidden list still counts.
- **Windows is unsupported for `--start-app`** (POSIX process groups);
  macOS is untested and has no system-chromium fallback paths.
- **Parallelism.** One run = one browser, sequential steps. Parallel
  spec execution (with session isolation) is future work.

## v0.2 roadmap (ranked)

1. **Run-over-run visual diff** -- perceptual hash to flag changed steps,
   pixel overlay in the report; informational, never gating.
2. **PR-comment / CI step-summary generator** -- pass counts + hero
   screenshots + report link.
3. **Timeline filmstrip strip** -- hover-scrub thumbnails across the
   whole tour.
4. **AI triage notes in-report** -- the /ccwalk:run skill already judges
   regression-vs-hiccup; persist that judgment into the report.
5. **Report history index on Pages** -- publish each run, index across
   runs.
6. **`ccwalk doctor --after '[...]'`** -- pre-actions so the doctor can
   inspect state behind interactions (drawers, modals).
7. **Before/after screenshot pairs** on interaction steps.
8. Web vitals per step (LCP/CLS via CDP); video chapter markers;
   narrated video re-render from the spec.

## Test coverage

99 unit tests (no browser needed: renderers are pure functions, Playwright
is mocked at the action layer, and the runner's context/video lifecycle is
driven against a fake browser), including regression tests for every
live-run lesson inherited from the predecessor system AND every finding
from the v0.1 adversarial review round: the wait-condition timeout
surfacing, video segment attribution under mid-group viewport changes,
the blocked-step cascade, doctor selector escaping, origin-scoped header
auth, --start-app imposter refusal and group teardown, the input_value
fix, the contiguity validator, escaping, and the embed mode. The bundled
demo tour is the browser-driving integration test, run in CI on every
push.

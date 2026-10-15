# My Day — test harness (repeating reminders)

My Day's earlier harnesses (the scratch files behind CLAUDE.md §14) never reached the repo. This one is committed and covers **repeating reminders** (set a reminder
once for chosen weekdays — it rings on those days until paused or deleted). Everything runs in Docker on **scratch** infrastructure — never the app's own `dusu-db-1`,
never real provider keys (`run.sh` / `run_real.sh` blank them; the bind-mounted `backend/` contains the real `.env`).

## One-time
The test image is the same one Resume Interview uses (the app image + `pypdf`); see `../resume_interview/README.md`. The browser tier also needs the Playwright
modules (`~/.cache/dusu-ri-pwrun/node_modules`, shared with the Resume Interview browser tier).

## Tiers
| # | What | Command | Needs |
|---|---|---|---|
| 1 | **Unit** — `clean_days`, `days_scheduled`, `days_text`, `next_rule_fire` (DST, half-hour zones, +13 h zones, a 4 000-case property test against an independent oracle), column widths of everything the feature writes, the occurrence key, rule / ring JSON, the lines DuSu is told (`life_lines`, incl. hostile titles) | `docker run --rm -v "$PWD/backend":/app -v "$PWD/tests":/tests dusu-ri-test python /tests/my_day/unit.py` | docker |
| 2 | **Scratch Postgres + the real HTTP layer + the real reminder engine** on a **fake clock** and a fake push sender: the old → new schema rehearsal; validation; IDOR + odd ids; the 30-rule limit; **the promise — three rules set once, 28 days driven through `tick()` / `materialize_all()`: every ring on its own weekdays, none on the others, none twice**; pause / resume / edit / delete; a ring ticked, snoozed, skipped, undone; follow-ups; push + the notification's Done token; Today / list / summary; DuSu's context; time zones, DST (New York, both ways), pause-everything, quiet hours; concurrency (12 simultaneous creates, 8 materializers, an edit racing the materializer — once by chance and once with the interleaving **forced**); tasks and habits repeating on weekdays; one-time reminders unchanged; export, delete-all, account deletion, the owner's wipe (every `pl_*` table) | `tests/my_day/run.sh selftest.py` (~35 s) | docker (starts and removes its own `postgres:18-alpine` + network) |
| 3 | **Do the tests catch a planted bug?** — copies the backend, plants ONE deliberate bug in the repeating-reminder code (weekdays ignored, delete leaves rings, an IDOR, no lock, ...), runs tier 2 against the copy, reports caught / survived | `tests/my_day/mutants.sh [M3 M5 ...]` (~35 s per bug) | docker |
| 4 | **Browser** — a real Chromium against the real app (uvicorn + scratch Postgres, **the real reminder loop on the real clock**): the form, set-once for Mon + Tue / Saturday / every day, tick / change / pause / resume / delete, a one-time reminder made to repeat, Today, **a repeating reminder really rings (the loop delivers it, the in-app card appears)**, Hindi, layout at 360 / 390 / 1280, an XSS canary, isolation | `tests/my_day/browser/run_real.sh` (~4 min: it waits for a real ring) | docker (`mcr.microsoft.com/playwright`, the test image) |
| 4b | **Browser: check and uncheck** — `browser/run_real.sh checks.spec.cjs` (~2 min): the owner's own sequence (a habit made on the Habits tab, checked on Today, tapped again), then every place a task / habit / goal / step / reminder can be checked and unchecked, across tabs, with real clicks; also what each control says it will do (Hindi too) and its layout at 360 / 390 / 1280. Shared helpers: `browser/lib.cjs` | docker (as 4) |

**Testing a BUILT image (before a deploy):** `MD_BACKEND=baked MD_TEST_IMAGE=dusu-backend:latest tests/my_day/run.sh selftest.py` (and the same variables for `browser/run_real.sh`) run the suites against the code **inside** the image instead of a bind mount - what runs in production is what was tested. Compare the image with the tested tree first (a sha256 over every `.py` / `.html` / `.js` / `.txt` in both). The deploy of 2026-10-15 did exactly this.

`.mutants/` and `.e2e/` are generated and git-ignored. Screenshots go to `~/.cache/dusu-md-shots/`.

## How the fake clock works (tier 2)
`tu.now_utc` is replaced by a function returning `CLOCK[0]`. `service._utc()`, `timeutil.local_today()` and `scheduler.tick()` all read it at call time, so a month of
days is driven in seconds. The scheduler's own `tick()` / `materialize_all()` / `deliver()` do the work — nothing is simulated except the clock and the push service.
`tick()` is global, so assertions are about the **rows of the learner under test** (`tick_user`), never about the pass's global counters.

## Notes that cost time once
* `docker run` needs `-i` to forward a here-doc to `python -` (without it the command prints nothing and "succeeds").
* The scheduler's `tick()` treats a ring more than 120 minutes late as "stale" (shown in the app only). A test that jumps the clock far ahead without ticking in between
  gets stale rows, not deliveries.
* A ring's key is `rr<rule id>:<local day>:<HHMM>`; a revived (cancelled → scheduled) ring keeps its row id, which is how "an edit re-plans the rings" is asserted.
* My Day shows **Hindi unless the learner chose English** (`dusu_lang`) and the Hindi / English switch is on (`settings.bilingual`): the browser tier switches it on and seeds `dusu_lang`.

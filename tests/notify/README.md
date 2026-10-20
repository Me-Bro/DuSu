# Notifications - test harness

Everything runs in Docker on **scratch** infrastructure - never the app's own `dusu-db-1`, never real provider keys (`run.sh` / `browser/run_real.sh` blank them; the bind-mounted `backend/` holds the real `.env`).
Same shape as `tests/my_day/` (see its README for the one-time Playwright / test-image setup).

| # | What | Command | Needs |
|---|---|---|---|
| 1 | **Unit** - the pure rules: who gets which nudge and when (windows, priority, caps, quiet hours, time zones, DST), the send-time re-check, the ignore-three back-off, every sentence in both languages (no unresolved placeholders, no gendered Hindi, limits, hostile names), the payload, the signed receipt token (and that it cannot be confused with My Day's), column widths | `tests/notify/run.sh unit.py` (the scratch Postgres it starts is unused) | docker |
| 2 | **Scratch Postgres + the real HTTP layer + the real engine** on a fake clock and a fake push sender (schema rehearsal, gates, validation, who-gets-what, idempotent planning incl. 8 workers, the send-time re-check, both languages, privacy, back-off, a late server, the weekly note, failures, receipts / taps, the test button, isolation, the rollout switch and the loop itself, data rights) | `tests/notify/run.sh selftest.py` (~20 s) | docker |
| 3 | **Do the tests catch a planted bug?** 21 deliberate bugs, one at a time, in a COPY of the backend; the suite must fail each | `tests/notify/mutants.sh [M3 M5 ...]` (~25 s per bug) | docker |
| 4 | **Browser against the real app** (uvicorn + scratch Postgres + the real loop, real Chromium; only the push subscription is faked) | `tests/notify/browser/run_real.sh` (~30 s); screenshots in `~/.cache/dusu-nt-shots/` | docker (Playwright image) |
| 5 | **Old = old** with the switch off: `git show HEAD:backend/test_client.html > tests/notify/.orig.html` then `ORIG_HTML_HOST=$PWD/tests/notify/.orig.html tests/notify/browser/run.sh oldnew.spec.cjs`. Text / element order must be identical, the DOM diff only the new hidden `nt*` markup. **The pixel tier is noisy**: the OLD page compared with itself differs on a random screen - run it twice | | docker |

Testing a BUILT image: `NT_BACKEND=baked NT_TEST_IMAGE=dusu-backend:latest tests/notify/run.sh selftest.py` (and the same variables for `browser/run_real.sh`).

Notes: the fake clock is `tu.now_utc` replaced with a function (the service's `_utc()` and the scheduler's `tick()` read it at call time); `tick()` is global, so assertions are about the rows of the learner under test. The planning pass and the send both check the rollout switch / blocked flag / the learner's own switch: a test must disable ONE layer to prove the OTHER (that is how mutants M6, M9, M18, M21 were first missed). In the browser tier `Notification.permission` and `navigator.serviceWorker.ready` are faked (service workers are blocked there) and the fake persists its permission and subscription in localStorage, like a real browser.

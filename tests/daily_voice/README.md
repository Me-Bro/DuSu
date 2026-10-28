# Daily Talk / Learn vs a locked screen - test harness

The bug (a tester's report): in Daily -> Chat with DuSu, lock the phone, unlock, and the mic and Reply are dead until the chat ends. The page used to run `stopAllVoice()` on "hidden" (recogniser dropped, `running = false`, socket closed and nulled) and nothing handled the screen coming back. Now Daily Talk and Learn are **paused**, not ended (`VP` in `backend/test_client.html`), and a socket that did not survive is replaced by a **quiet reconnect** (`start {reconnect: true}` -> `daily_resumed`, no greeting, no model call, only new turns count). See CLAUDE.md section 21.

Everything runs in Docker on **scratch** infrastructure - never the app's own `dusu-db-1`, never a real provider key (the scripts blank every key) and **no route to the internet** (the scratch Postgres network is `--internal`). Providers are the scripted fakes of `tests/keys/world.py`; the browser spec reuses `tests/keys/e2e_server.py` (the real app + a scratch Postgres; it seeds learners `lk1`..`lk10` for this spec).
One-time setup (the Playwright modules and the `dusu-ri-test` image) is the same as `tests/notify/README.md`.

| # | What | Command |
|---|---|---|
| 1 | **Server** - the real `/ws/interview` handler: `ping` -> `pong` (and an unknown frame type is still ignored); a Daily `start` with `reconnect: true` + a non-empty `resume` = `daily_resumed`, NO model call, the replayed turns reach the model as context, and only turns spoken AFTER it are rewarded (finishing straight away writes no XP / summary; one new turn = +20 once); no flag / a flag that is not the boolean `true` / an empty resume / another mode = exactly today's behaviour | `tests/daily_voice/run.sh ws_selftest.py` (~1 min) |
| 2 | **Browser against the real app** (real Chromium -> a WebSocket proxy -> the real server): the lock in every state (idle, listening, DuSu speaking her reply or her greeting, thinking with the answer landing while locked / after the unlock), a socket that died while locked, a **half-open** socket (frames silently dropped), a long lock on a healthy socket (ping), the 10-minute grace timer (Playwright clock), a line that was in flight, rewards never paid twice, the mic after a key-limit pop-up, Learn, and **pins** (Face-to-Face still stops on lock; a never-locked Daily session sends exactly the old frames) | `tests/daily_voice/browser/run_real.sh lock.spec.cjs` (~3 min); `ONLY=A1,B2 ...` runs just those scenarios |
| 3 | **Do the tests catch a planted bug?** 6 server + 16 client deliberate bugs, one at a time, in a COPY of the backend; each runs the tier / scenarios that should notice it | `tests/daily_voice/mutants.sh [S2 K5 ...]` |

Testing a BUILT image: `DV_BACKEND=baked DV_TEST_IMAGE=dusu-backend:latest tests/daily_voice/run.sh ws_selftest.py` and the same variables for `browser/run_real.sh`.

"Old = old" for the client is measured with the Keys harness against the commit before this change: `git show efdee9b:backend/test_client.html > tests/keys/.orig.html` then `ORIG_HTML_HOST=$PWD/tests/keys/.orig.html tests/keys/browser/run.sh oldnew.spec.cjs`.

## How the lock is simulated (`browser/lib.cjs`)
* `window.__setHidden(true|false)` overrides `document.hidden` / `visibilityState` and fires `visibilitychange` - what Chrome does on a lock. The fake `SpeechRecognition` refuses to start on a hidden page and ends a live recognition when the page becomes hidden, like a real browser; `window.__hold = true` makes it listen until the spec speaks (`window.__say`) - the state a learner is in when the screen locks.
* The speech stub has a controllable length (`__ttsMs`) and records what was spoken while hidden (`__spokenHidden`).
* `L.proxy(ctx)` sits between the page and the real server (Playwright `routeWebSocket`): every frame is recorded per connection, inbound frames can be HELD (`c.hold`, `c.release()`), the connection can be KILLED (`c.kill()`), or FROZEN (`c.frozen = true`: both directions dropped while the page still believes the socket is open).
* Scenarios that need time to pass (the ping after a long lock, the 10-minute grace timer) install the Playwright clock (`{ clock: true }`) and `fastForward` it.

## Notes that cost time once
* A scenario that kills a socket must wait for the server's end-of-session save (itself a model call) before it measures "no model call for the reconnect": poll the learner's XP.
* Wait for the second connection's `start` frame before reading it - the connection record exists a moment before the page sends the frame.
* The speech watchdog in `say()` is `3500 + len * 90` ms: a "nothing is spoken while hidden" check must keep the page hidden for longer than that (A3 locks for 5 s).
* Each scenario uses a learner of its own (`lk1`..`lk10`); the rewards scenarios (C1, C2) need one to themselves because they compare XP.

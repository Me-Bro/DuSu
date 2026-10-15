# Resume Interview — test harness

The earlier feature harnesses (My Day, Practice Room) were scratch files that never reached the repo. This one is committed. Everything runs in Docker on
**scratch** infrastructure — never the app's own `dusu-db-1`, never real provider keys (except the owner-run tier 3, which is explicit about it).
Fixtures are **synthetic**; real resumes from spike S1 are never committed.

## One-time: the test image
The app image plus the one new dependency (so it works before `docker compose up --build`):

```bash
printf 'FROM dusu-backend:latest\nRUN pip install --no-cache-dir pypdf==6.20.1\n' | docker build -t dusu-ri-test -f - .
```
(If `dusu-backend:latest` does not exist, run `docker compose build backend` first — then the image already contains `pypdf` from `requirements.txt`.)

## Tiers
| # | What | Command | Needs |
|---|---|---|---|
| 1 | **Unit** — pure logic: cleaning, redaction (Indian formats, year runs), the sandboxed extraction child (PDF / DOCX / zip bomb / encrypted / hung / empty environment), match score + evidence ladder, edits, question validation + bank, answer scoring, quote verification, the computed report, prompts, the engine's retry ladder, the shared `_mark_cooldown` fix | `docker run --rm -v "$PWD/backend":/app -v "$PWD/tests":/tests dusu-ri-test python /tests/resume_interview/unit.py` | docker |
| 2 | **Scratch Postgres + the real HTTP layer**, stub model + stub speech-to-text: the whole flow, *a duplicate request = exactly one model call* (double analyze / start / answer / next / finish), XP once, two-learner IDOR matrix, switch off → 404 (export / delete excepted), caps, NUL / surrogates, data rights, every delete path, introspection (enumerated values fit their columns) | `tests/resume_interview/run.sh selftest.py` | docker (starts and removes its own `postgres:18-alpine` + network) |
| 3 | **Real model** on **synthetic** documents — **owner-run, spends a few dozen model calls**: JSON validity, requirement-status stability, match band for unrelated fields, plan quality, strong-vs-weak gap, prompt-injection resilience, Hinglish script, latency per attempt | `docker run --rm --env-file backend/.env -e DATABASE_URL= -v "$PWD/backend":/app -v "$PWD/tests":/tests dusu-ri-test python /tests/resume_interview/real_model.py 3` — add `-e GROQ_API_KEY=` to test the Gemini-only chain | provider keys in `backend/.env` (passed as env vars, never printed) |
| 4 | **Browser** (Chromium, fake microphone, stubbed Groq). *Mock tier* (a stand-in for `/rinterview/*` written from the contract): `browser/run-all.sh` (~18 min). *Real tier* (the real app + a scratch Postgres + the stub model, Chromium inside the server's network namespace): `browser/run_real.sh` | see `browser/README.md` | docker (`mcr.microsoft.com/playwright`; the real tier also needs the `dusu-ri-test` image) |
| 5 | **Old = old** — registry / cooldown / XP table / labels identical to `HEAD` with the switch off; the client's old screens identical before / after | `mkdir -p tests/resume_interview/.head && git show 70455da:backend/app/home_content.py > tests/resume_interview/.head/home_content_head.py && git show 70455da:backend/app/life.py > tests/resume_interview/.head/life_head.py && git show 70455da:backend/app/providers/openrouter_provider.py > tests/resume_interview/.head/provider_head.py` then `docker run --rm -v "$PWD/backend":/app -v "$PWD/tests":/tests dusu-ri-test python /tests/resume_interview/parity_server.py` (client side: `browser/`) | docker, git |

`.head/` is generated and git-ignored. `70455da` is the last commit BEFORE this feature (HEAD already contains it), so the proof stays "old = the code before the feature".

## What the independent review added (2026-10-15)
* `unit.py` times every entry point that touches user text on 25 adversarial shapes (spaces, `a@a@`, `www.` spam, label spam ...) - any regex that goes quadratic again fails
  it - and runs a seeded property test (3000 random resume-like documents: `redact()` never raises and is idempotent).
* `selftest.py` has a "review" section: odd ids / deep JSON -> 404 / 422 (never 500), one parse at a time, fresh / 100 s / stale claims, the same resume + job analysed twice at once,
  a blocked account's data rights, forged timestamp rows, an AI outage on every answer (Finish still works, "not scored", XP with the components UNSCORED), the XP-once guard when a
  failure lands after the XP row is committed, delete-all, `/state` (`active` beyond page one, `has_more`).
* `real.spec.cjs` part F: the same outage through a real browser.

## Notes that cost time once
* An `http://<container-name>` origin is an insecure context: `navigator.mediaDevices` does not exist, so there is no microphone. `browser/run_real.sh` starts Chromium with
  `--network container:<the server>` so the page is `http://localhost:8000`.
* The client's own-keys gate needs two keys AND `dusu_keys_owner` = the account's email in a test seed; a learner with neither a Groq key nor keys stored server-side gets the
  "add a free Groq key" card instead of recording (that is the design - `/me.ri_server_stt` is only true for accounts the server can transcribe for).
* `run.sh` blanks `GROQ_API_KEY / GEMINI_API_KEY / OPENROUTER_API_KEY / GITHUB_TOKEN` because the bind-mounted `backend/` contains the real `.env`; `selftest.py` refuses
  to start if any provider key is configured. (The first draft of tier 2 made a real Groq call and a real Gemini call for exactly that reason.)
* Docker here can only bind-mount paths under the repo, not `/tmp`.
* The chain treats "all providers/models unavailable" as quota (429 `quota`), like every other feature; use any other message to exercise the 502 path.
* `unit.py` / `selftest.py` / `real_model.py` print `PASS` / `FAIL` per check and exit non-zero on any failure.

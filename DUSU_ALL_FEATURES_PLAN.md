# DUSU — Make every feature real: Home that answers, Practice Room with Viva, My Day (routine) — Plan + status

> **Status 2026-10-11: ALL THREE WORKSTREAMS BUILT, DEPLOYED AND LIVE-CHECKED (Practice Room + planner switches = `owner`; flip to `on` from the dashboard when ready).** Owner: "where is viva, practice option? … is Know About showing *coming soon* … make sure it is fully configured and all features start working … in Home → Start Speaking nowhere to go and no AI buttons needed — we can ask questions: what is the time, routine, my progress … make a solid plan and implement".
> Status of each stage: §7.

## 0. How the message was read
| Phrase | Decision |
|---|---|
| "where is viva, practice option?" | The **Practice Room** (presentation / **viva** / discussion / speech / seminar / custom). It is switched **OFF** (default) so it is invisible; and only *Presentation* is built - Viva, Discussion, Speech, Seminar, Custom show "Soon". → switch it on for the owner **and build the other five** |
| "is Know About showing *coming soon*" + "fully configured, all features should start working" | Know About lists **Goals & Daily Planning = Coming soon** (the planner is only a plan). → build **My Day** (tasks, habits, goals, reminders) so nothing there says "coming soon" any more for what exists |
| "in Home → Start Speaking no where need to go, no AI need to show here, we can ask: what is the time, routine, my progress related" | The Home chat must **answer in place** - the clock/date, today's routine/plan, progress and practice time - from real data, instead of replying "go to the Journey page / try Daily Talk" and drawing feature buttons. Buttons only when the learner asks to *do* something that lives elsewhere (practise, interview, translate, rehearse a viva/presentation) |
| "make solid plan and implement" | Standing workflow: plan → build → push → SSH deploy → verify live, no approval round |

## 1. Audit (measured 2026-10-11)
| Fact | Evidence | Consequence |
|---|---|---|
| Practice Room is **off for everyone**, owner included | prod `settings` table holds only `level_test=off`; code default is `off` | Nothing to see; also hidden from Home tiles and Know About |
| Only `presentation` is enabled | `practice.ENABLED_KINDS = ("presentation",)`; hub draws the other five as "Soon" | Viva etc. must be built |
| The server's **Groq key is dead (403)**; Gemini, OpenRouter, GitHub keys are alive | read-only probe from the container | Presentation transcription (Groq Whisper) cannot work for accounts on DuSu's keys. **Spike:** Gemini transcribes Chrome's `audio/webm` (opus) accurately with segment timestamps (23 s clip: flash-lite 4 s, flash 27 s) → add a **Gemini fallback** to `/practice/transcribe`; the scorer already degrades gracefully without word timestamps ("model's read only") |
| Home chat has **no clock**: the prompt gets only a time-of-day word and the hour | `home_system(time_of_day, hour)` | "What time is it?" cannot be answered |
| Home numbers need the **`life_context` switch** | `main.py`: `life.build` only if `life_context_enabled` | "My progress" works for the owner only because that switch defaults to owner |
| "Routine" has no data behind it | no planner tables; the Home prompt says "no saved tasks" | The planner must exist for "what is my routine" to be answerable |
| Home replies end with feature buttons / "go to …" | `home_content.actions`, `_HOME_RULES` | Tighten the rules; buttons only for do-something requests |

## 2. Decisions
| # | Decision |
|---|---|
| D1 | **Home answers in place.** Server computes the learner's local clock each turn (client sends its UTC offset in `start`; default IST) and gives the model `RIGHT NOW`. Informational intents (time, routine/plan, progress) return **no buttons**; the prompt forbids "go to X" for something it can answer |
| D2 | Home's numbers no longer depend on `life_context` - Home is its own switch (`home_ai`) with its own privacy toggle. Talk / Daily Talk keep the `life_context` switch exactly as before |
| D3 | **Practice Room on for the owner now** (`practice_room=owner`). "Everyone" stays the owner's call: it records audio, so the Play Data-safety form must match first (`DUSU_PRACTICE_ROOM_PLAN.md` gate) |
| D4 | **STT fallback**: `/practice/transcribe` tries Groq when a key exists, else (or on 401/403/429/5xx) **Gemini** with the account's key chain; same JSON shape, `words:[]`/`segments:[]` (timing then "model's read only"), engine flag recorded in the report so the UI can say pace/pauses are estimates |
| D5 | **All six kinds live.** Monologue kinds (presentation, **speech**, **seminar**) use the existing record → transcribe → analyse pipeline. Conversation kinds (**viva**, **discussion**, **custom**) are a new turn-taking engine on the existing WebSocket (`mode:"practice"`, voice in/out like Interview): an examiner / participant / role persona, N rounds, then a scored report saved as a normal Practice attempt (history, XP, missions, badges) |
| D6 | **My Day = DUSU_GOALS_PLAN.md P0-P3** (tables, tasks, goals by hand, Today, DuSu knows the plan, reminders with in-app + Web Push + test button, habits, recurring tasks). **Not in this pass:** AI goal drafting / natural-language add (P4), recovery + evening review (P5) - Know About copy claims only what exists |
| D7 | Switch `settings.planner` off / owner / on; set to **owner** after the deploy is verified. Scheduler idles when off. Push is opt-in; unverified on a phone until the owner runs the test button |
| D8 | Hindi / English: My Day is a **new feature** → follows the Hindi/English choice (own `hi`/`en` table + the same pill), default Hindi, task titles never translated |
| D9 | Registry (`home_content.FEATURES`) stays the single source for Know About, the Home tiles and the model's catalogue: `goals_planning` becomes `live` with route `/my-day` **when the learner has `planner`**, "coming soon" otherwise; Practice Room text updated; a new tile icon |
| D10 | Everything new ships behind a switch that is **owner-only until the owner flips it**; old features are untouched (the language-scope A/B harnesses are re-run) |

## 3. W1 - Home answers (server + client)
- `WS start` adds `tzmin` (minutes east of UTC). `Session(tzmin=)`; `home_turn` builds `RIGHT NOW` each turn: weekday, date, 12-hour time (+ part of day) in the learner's offset.
- `home_system(..., now_text, planner_on)`; `_HOME_RULES`: answer time/date from RIGHT NOW; routine from TODAY'S PLAN lines when the planner is on, else say plainly there is no My Day yet; progress from THEIR NUMBERS (incl. minutes practised today/this week); "do not send them to another screen for something you can answer here"; suggest a feature only for a do-something request.
- `home_content`: `INFORMATIONAL` intents (`daily_plan`, `goal_progress`, `feature_discovery` keeps Know About) get no default buttons; model `suggest` is dropped for them.
- Numbers: `life.build` for Home regardless of `life_context`; `life.EXTRA_LINES` (planner) appended.
- Client: chips become **Time / My routine / My progress / Practice**; the chat sends `tzmin`.

## 4. W2 - Practice Room, all kinds
- Switch: `practice_room=owner` in prod settings after deploy.
- `/practice/transcribe`: Groq first when keyed, Gemini fallback (flash-lite for English, flash for Hindi/Hinglish; Hindi words in Devanagari, English words in Latin); 24 MB cap, 40/day cap unchanged; `_pr_server_stt` true when either key exists; the report carries `stt_engine`.
- `practice.ENABLED_KINDS` = all six; `practice_analysis_system(kind, …)` already labels speech/seminar.
- **Conversation engine** (`Session(mode="practice", kind, topic, lang, level, rounds, persona)`): prompts `practice_talk_system(kind, …)` (viva examiner: one question at a time, adapts, ends with the marker after N rounds; discussion: moderator + one participant; custom: guarded role-play from the learner's scenario text, treated as data), parked Hindi building blocks reused for Hindi/Hinglish. `practice.analyze_talk(...)` → the same report shape as a presentation (`categories`, `strengths`, `improvements`, `content_gaps` = **questions to revise**, verified grammar quotes for English), saved with `db.save_practice_attempt`, XP via `award_speaker_progress(kind)`, missions, badges, history.
- Client (`PR`): hub shows six live kinds (no "Soon"); a talk-setup (topic, language, level, rounds, scenario for custom); the live conversation reuses the `#session` voice loop (`startSession("practice")`) and ends in the Practice report screen; category labels added.

## 5. W3 - My Day (see DUSU_GOALS_PLAN.md for the long form; deviations here)
| Piece | This pass |
|---|---|
| Tables (new, `pl_*`, `create_all`) | `pl_prefs`, `pl_goals`, `pl_milestones`, `pl_tasks`, `pl_habits`, `pl_habit_logs`, `pl_reminders`, `pl_push_subs`, `pl_events` (no `pl_goal_versions`: no AI drafts yet) |
| Server | `backend/app/planner/` - `timeutil` (tz, recurrence, DST), `rules` (status, progress, consistency), `models`, `service` (CRUD, idempotent, ownership), `scheduler` (15 s loop, `FOR UPDATE SKIP LOCKED`, quiet hours, follow-ups, stale, backoff), `push` (VAPID in settings, `pywebpush==1.14.1`), `api` (`/planner/*`), `life_lines` |
| Client | `PL` module: Today · Tasks · Goals · Habits · Reminders · Settings, Add sheet (manual forms), reminder cards (Done / Later / Skip), in-app polling, service-worker `push` + `notificationclick`, Home card + tile + More row, route `/my-day*` |
| DuSu | Home + Talk/Daily get `Today's plan / Habits / Goals / Next reminder` lines (EXTRA_LINES, `(uid, email)`); DuSu **reads** the plan, never claims to have changed it |
| Data rights | export JSON, delete-all, `delete_user` / `admin_wipe_users` include the new tables |

## 6. Verification
| Tier | What |
|---|---|
| Pure logic | time/recurrence/DST, status derivation, progress/consistency, quiet hours, action tokens, practice report shape, Home now-text |
| Server on a scratch Postgres | every endpoint through HTTP incl. a second-user IDOR matrix; idempotency; scheduler against a fake push sender; restart-safety; WS `practice` flow with a stub model and with the real model; STT fallback against the real Gemini |
| Browser | each new screen in Chromium (phone + desktop, Hindi + English), the Practice hub with six kinds, the Home chat answering; **the language-scope A/B harnesses re-run so old features stay identical** |
| Real stack | real browser → real server → real model for: Home "time / routine / progress", a Viva session end to end, a Presentation via the Gemini STT path (synthetic English speech), a My Day task + reminder |
| Live | smoke on both hostnames; the new bytes through the browser suites |
| **Not verifiable here** | a real phone: recording permission / Wake Lock, Hindi/Hinglish transcription quality, Web Push when the app is closed (battery killers), the grid on a handset |

## 7. Status

| Stage | State | Evidence |
|---|---|---|
| W1 Home answers in place | **built, verified, deployed** (commit `a630db6`) | 172 pure checks · 95 scratch-DB checks · 123 + 55 + 28 browser checks · **real model** (`home_real.py`): the exact time + weekday from the device's own offset (also UTC-5), the real streak and minutes (no invented numbers), the routine answered honestly, plain chat with no buttons, an interview request still gets the Interview button, the learner's name kept in Latin letters |
| W2 Practice Room - all six kinds | **built, verified, deployed** (commit `a630db6`, `practice_room=owner`) | `practice_talk.py` (viva / discussion / custom persona + scorer), WS `mode:"practice"`, Gemini STT fallback, six live tiles, badges. 105 pure checks · 53 scratch-DB checks incl. the **real** Gemini transcription of a spoken English clip · 87 + 39 browser checks · **real model**: strong viva 76-85, weak viva 24-27, Hinglish discussion 79-81, medical-advice and impersonation role-plays declined. A romantic role-play is refused **before** any model runs (measured: the model played it when only the prompt said no) |
| W3 My Day | **built, verified, deployed** (commit `85f0b86`; `planner=owner` set after the live checks) | package `backend/app/planner/` (9 new `pl_*` tables, 15 s reminder loop with Postgres as the queue, Web Push with signed one-action tokens, `/planner/*` API, DuSu reads the plan), client `PL` (Today / Tasks / Goals / Habits, reminders, settings, add + edit sheets, floating reminder card on any screen), Home card + tile + More row, owner dashboard switch + engine health, Hindi + English. 66 pure checks · **130 scratch-Postgres checks** through the real HTTP layer + the real scheduler (fake clock, fake push sender): idempotency, cancel-on-complete / delete / reschedule / pause, quiet hours, stale, follow-ups -> expiry, push accepted / gone / backoff / cap, crash reclaim, disjoint concurrent claims, a **17-probe two-learner IDOR matrix (all 404)**, blocked account, export / delete-all / account deletion / owner wipe, DuSu's plan lines, Home wiring, the loop delivering end to end · **real browser -> real server -> real loop `pl-e2e.cjs` 45/45** · realistic-data look in Hindi + English at 360 / 390 px + desktop `pl-look.cjs` 69/69 · old -> new schema migration rehearsal on a scratch DB (adds exactly nine tables + the partial unique indexes, leaves the existing user untouched, idempotent) |

**Live (2026-10-11):** new image healthy on the host (the requirements change made the first build slow - ~11 min of pip; the old container served throughout), the nine `pl_*` tables created by `init_db`, md5 of the 11 shipped files identical to HEAD, `hm-live.cjs` + `pl-live.cjs` (44 anonymous read-only checks, 22 per hostname: every `/planner/*` endpoint 401, forged action token 401, `/my-day` deep link, `sw.js` byte-identical with push + notificationclick, privacy + account-deletion text) pass on **both** hostnames. No authenticated call was made against production (no token minted); the owner's own login is the first real one.

**Not built in this pass (so no copy claims it):** AI parsing of a sentence, AI goal drafting / replan / split, the recovery card, the evening review, voice capture ("DuSu, remind me ..."), the Career-roadmap bridge. DuSu **reads** the plan and never changes it. **Not verified:** push while the app is closed on a real phone (the §7.2 matrix of `DUSU_GOALS_PLAN.md`) - the owner runs Settings -> "Send me a test reminder" on the handset before anything is promised.

**Measured along the way (kept so nobody re-discovers them):** the model, told only in the prompt to refuse "act as my romantic girlfriend", **played along** - a keyword filter now runs first and the prompt has a STEP ZERO check as the second layer. The viva examiner repeats a question once when the answer does not address it (intended). After a scoring failure the learner can tap **End** again on the same conversation (the server resets `practice_done`). Old-feature parity: server A/B 180/180 scenarios identical (HEAD vs working tree, switch on and off), client A/B 89/89 identical in 7 variants.

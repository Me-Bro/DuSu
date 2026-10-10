# DUSU — Goals, Habits & Smart Reminders ("My Day") — Plan

> **Status 2026-10-10: PLAN ONLY. Nothing in this document is built.**
> Written with the superpowers brainstorming flow: audit the real repo → take the open decisions → design → stop for review.
> Part 1 of the same request, **"DuSu knows your data"**, *is* built and live (CLAUDE.md §10, commit `fc32d1b`) — this module plugs into it (§10).
> **Waiting for the owner's go.** Reply **"go"** (all phases, in order) or **"go P0–P2"** (reminders first — recommended, §13) and the chosen phases get turned into a task-by-task implementation plan and built behind a switch that ships **OFF**.
>
> Also asked: *"is the viva / presenting feature done?"* — **Presentation is built and live but switched OFF** (Practice Room, commit `acfc04b`). Viva, seminar, speech and discussion are **not** built: the Practice Room shows them as "Soon" (`practice.ENABLED_KINDS = ("presentation",)`).

## Contents
0. TL;DR · 1. Your spec vs. this repo (+ audit) · 2. Scope & acceptance criteria · 3. Not in V1 · 4. Screens & flows · 5. Domain model · 6. Reminder engine · 7. Channels & Android reality · 8. API contract · 9. AI design · 10. DuSu integration · 11. Privacy & security · 12. Verification plan · 13. Phases & tickets · 14. Rollout & metrics · 15. Risks & open questions · Appendices A–C

---

## 0. TL;DR

**What it is.** One module with four connected parts — **Tasks, Goals, Habits, Reminders** — on one set of tables and one **Today** dashboard, and DuSu (the companion) knows all of it. The English-learning app is untouched.

**Principles (your spec §18, unchanged):** one source of truth · reliable reminders first · AI proposes, the user approves · no guilt-based coaching · one daily dashboard · user control over every reminder · build on existing DuSu · measure outcomes, not notification volume.

**Five facts about *this* repo that shape the design** (each verified 2026-10-10; details in §1.2):

1. **There is no scheduler anywhere in the backend** — one `uvicorn` process, no cron, no queue; the only startup hook is `init_db()`. Reminders need one → an in-process asyncio loop over a Postgres table (`FOR UPDATE SKIP LOCKED`). No Redis, no new container (your spec says not to add one unless needed). §6
2. **The installed Android app is a TWA with no notification delegation and no JS bridge** (manifest checked: no `DelegationService`). The only way a *closed* app can learn about a user's own task is a server-sent **Web Push**. Whether that works inside the installed app is **unverified** → the plan builds a "send me a test reminder" button and runs phone spikes *before* anything is promised. §7
3. **The app's day boundary is a fixed IST everywhere** (quota day, streak, weekly league). Reminders are wall-clock by nature, so this module uses a **per-user IANA timezone** — planner-only; the existing IST logic is left alone. §5.4
4. **Dependency traps found:** `pywebpush` ≥ 2.4 requires `cryptography ≥ 47`, but we pin `44.0.0` (it seals BYOK keys) → pin **`pywebpush==1.14.1`** (pip dry-run resolves cleanly with 44.0.0). The local Windows venv has **no timezone database** (`ZoneInfo('Asia/Kolkata')` fails) while the production container has one → add `tzdata` to `requirements.txt`.
5. **"plan" already means *subscription plan*** here (`db.get_plan`, `PLAN_LIMITS`, `users.plan`). Nothing in this module is called "plan"; code prefix is `planner` / `pl_`, and AI roadmap history is `pl_goal_versions`.

**Recommendation.** Build **P0–P2** first (tables, tasks, goals-by-hand, Today, DuSu knowing the plan, then the reminder engine + push + phone test). Look at the phone results. Only then spend effort on habits, the AI planner and recovery (P3–P5). Size: roughly **5–6k lines** all-in (≈ twice the Practice Room); P0–P2 is about 45% of it.

### Decisions I took (overrule any — each is one line to change)

| # | Decision | Why |
|---|---|---|
| D1 | Name **"My Day"**; entry = Home card + More-sheet row; **no new bottom-nav tab** in V1 | The 6-tab nav is full at 440 px; the Practice Room used the same entry pattern (`#prHomeCard`) |
| D2 | Rollout switch `settings.planner` = **off (default) / owner / on**; no tester tier | Settings value column is 255 chars (can't hold an email list); a tester tier would need a tiny table — say if you want one |
| D3 | Defaults: reminders on, **push only after an explicit opt-in**, quiet hours 22:00–07:00 on, **1 follow-up** after 30 min, snooze 30 min, morning briefing **off**, evening review **off** | "A high number of notifications is not a success metric" (your spec §16) |
| D4 | **No XP / coins / English-streak coupling** in V1; habits show consistency %, streak is secondary; DuSu may *celebrate* via an achievement line | The English progression is a separate currency (Speaker Progression plan, Option C); mixing them invites gaming |
| D5 | **Voice capture of tasks = V1.5**, not V1; the quick-add box does accept the mic via the existing speech recogniser | Your spec lists it under Version 2; V1 DuSu *knows* the plan but must never claim to have changed it |
| D6 | Notification text shows the task title; a **"hide details on lock screen"** toggle swaps it for "You have a reminder" | Titles can be private ("call lawyer") |
| D7 | **Per-user IANA timezone**, auto-detected from the browser, editable; default `Asia/Kolkata` | §0 fact 3 |
| D8 | Retention: tasks/habit logs/goals kept until the user deletes; `pl_events` 180 days; terminal reminders 90 days | Bounded growth, user-controlled history |
| D9 | Limits: 10 active goals · 500 open tasks · 30 habits · 20 AI calls/day · 100 user-created reminders/day · 5 push devices | Abuse + free-LLM-quota protection |
| D10 | `pywebpush==1.14.1` + `tzdata`; **do not bump `cryptography`** | §0 fact 4 |
| D11 | Scheduler lives in the web process; revisit only if uvicorn ever gets multiple workers (it is `SKIP LOCKED`-safe anyway) | No new infra on a shared box |
| D12 | UI English; the AI parser accepts English / Hindi / Hinglish input (Latin or Devanagari) and answers in English | Matches the product's audience without a second UI language |
| D13 | iOS is **not targeted** (Android-first product; iOS web push needs Add-to-Home-Screen) | Scope |
| D14 | Condition reminders ("when I finish trading…") get an optional **fallback time** ("…or at 9:30 PM anyway") so they can never silently never fire | Your spec makes "tap *Trading finished*" the MVP trigger; without a fallback a forgotten tap = a forgotten reminder |

---

## 1. Your spec vs. this repo

### 1.1 Adaptations (the spec itself says "adapt this plan to the real codebase rather than creating a parallel system")

| Spec says | DuSu reality | This plan |
|---|---|---|
| Node.js + TypeScript, existing ORM | **Python 3.12, FastAPI, SQLAlchemy 2 async + asyncpg**, one 7.6k-line client file | Python module `backend/app/planner/` + a client module `PL` |
| Redis / persistent job queue | none; one process | Postgres table as the queue (`SKIP LOCKED`) + in-process loop (§6) |
| `POST /api/goals` … | no `/api` prefix; endpoints are `/practice/…`, `/lesson/…` | `/planner/…` (§8) |
| Existing auth | Google sign-in → 30-day HMAC session token; `token` in body/query or `Authorization: Bearer`; roles by email; blocked-status gate | Same helpers; **every** query filters by `user_id` |
| Database schema | `create_all` creates **missing tables only**; never adds columns | **All-new `pl_*` tables** → no `ALTER` on any existing table |
| New AI provider? "don't" | LLM chain gemini→groq→openrouter→github, BYOK per account (`resolve_keys`), `llm.assess(..., temperature=)` | Reuse it; AI endpoints are BYOK-gated, everything else works with no keys |
| Web push / in-app / native | PWA + TWA; no push code exists; the TWA's native layer only has a generic 4-hourly "practice reminder" alarm | Web Push + in-app (§7); native layer unused |
| Analytics | none | `pl_events` + an admin card (§14) |

### 1.2 Architecture audit — verified facts and what each forces

| Layer | Verified fact (2026-10-10) | Consequence |
|---|---|---|
| Process | `Dockerfile` CMD `uvicorn app.main:app` — one worker; compose = `backend` + `db`; `startup` hook only calls `db.init_db()`; `db.py` itself notes "No cron on this stack" (season close is owner-triggered) | Scheduler is new; start it from `startup`, make it idempotent and crash-proof |
| DB | SQLAlchemy 2 async, default pool (5 + 10 overflow); `init_db` = `create_all` + explicit `ALTER … IF NOT EXISTS` + `CREATE INDEX IF NOT EXISTS`; `Memory.facts` is one hot JSONB doc, row-locked (`_get_or_make_memory`) | New tables only; prefs in their own small table (the scheduler reads them on every send — not from the hot doc); partial unique indexes created explicitly |
| Time | `db._ist_now`, `_quota_day`, `_ist_week_start` — fixed UTC+5:30 everywhere | Planner-only per-user tz via `zoneinfo`; `tzdata` pinned for dev machines (the prod image already has `/usr/share/zoneinfo` — checked) |
| Auth & gates | `_practice_claims` / `_practice_gate`: flag → blocked → BYOK (`resolve_keys`, 402 `keys_required`); `_safe_err` keeps transcripts out of logs; Settings table + `_cached` (60 s TTL) for switches | Copy the pattern exactly: `_planner_gate`; AI endpoints add BYOK, others don't |
| Switches | `practice_room`, `life_context` already use `off/owner/on` + dashboard select + `/me` field | `planner` is the third; `/me.planner` (bool for that user) |
| Client | One file; **unscoped CSS** (the `.rec` collision happened once); `ROUTES`, `NAV_TAB`, `pathForScreen`, `show()`, `navTo()`; `userState` from `/me`; bottom nav = Home · Journey · Daily · Practice · Ranks · More; More sheet rows; Home entry card pattern; `PR` IIFE module as the template | `pl-` CSS prefix, `#pl*` ids, `PL` module; entries hidden until `userState.planner` |
| Service worker | `sw.js` (v19): allowlist caching, network-first navigation; **no `push` / `notificationclick` handlers** | Add them; bump `CACHE` |
| Android | TWA `com.dusu.app` v1.1 (versionCode 2), androidbrowserhelper 2.7.0, SDK 36; manifest has `POST_NOTIFICATIONS`, boot + reminder receivers, **no `DelegationService`**; `Notifications.kt` = `AlarmManager.setInexactRepeating` every 4 h, generic copy, no access to user data; a TWA has no JS↔native bridge | Native alarms can't know a user's tasks → Web Push is the only closed-app route; delegation may need a new AAB (§7.3) |
| Overlaps | Career Roadmap (`facts.career_roadmap`: phases → stages with done toggles, `/career/*`); weekly missions; Home event banner (`facts.events`, e.g. an interview date); Daily Talk `daily_context.plans`; mood check-in; `next_hook` | Career stage → "Make this a goal" bridge (P4); event banner can offer "Add prep goal"; no duplicate concepts |
| Part 1 | `life.EXTRA_LINES` hook exists and is deployed | The planner appends its lines there (§10) |
| Play | Closed test in progress; Data-safety form must match reality | Module ships dark; privacy pages + Data-safety updated *before* it goes live (§11) |

---

## 2. Scope & acceptance criteria (V1)

Every line is a testable statement; §12 maps each to a verification tier.

### A. Tasks
- **AT1** A task is created from one sentence **or** a form needing only a title. Due date/time, priority, goal link, notes, repeat, reminder are optional; DuSu asks only for what a reminder can't work without.
- **AT2** Status is **derived** by one function: *upcoming · due soon (≤ 3 h) · overdue · snoozed (chip) · done · skipped*. "Today" = the user's local date.
- **AT3** A task never disappears because a notification was dismissed or snoozed. It leaves the open list only by done / skip / delete (or its recurring series ending).
- **AT4** Up to **3 pinned** tasks per day, shown first; a pin expires at local midnight.
- **AT5** Reschedule keeps `orig_due_at`, appends to a history list, and never creates a duplicate (recurring: keyed by the *original* occurrence date).
- **AT6** Completing a task is one transaction: task → done, its pending reminders cancelled, milestone/goal progress recomputed, an event written. A repeated request returns the same state and writes no second event.
- **AT7** Condition tasks show a chip (e.g. **▶ Trading finished**); tapping it schedules the reminder (idempotent). Nothing fires without the tap, except the optional fallback time (D14).

### B. Reminders
- **AR1** The first reminder fires at the chosen **local** time (within one scheduler tick, ≤ 30 s).
- **AR2** At most `followups` (0–2, default 1) follow-ups, `gap` apart (default 30 min); then it stops, and the task is **overdue and visible** — no endless pushes.
- **AR3** Actions: **Done · Later (snooze) · Skip**, plus **Reschedule** in-app. Each is idempotent.
- **AR4** Quiet hours defer to the quiet end; DST-safe; a reminder > 120 min late (server was down) is **in-app only**, never a stale push.
- **AR5** Survives refresh, closed tab, app restart and **server deploys** (rows live in Postgres; reconciled on boot).
- **AR6** No duplicates: unique occurrence key + `SKIP LOCKED` claim + push `tag`.
- **AR7** Permission denied/revoked is shown clearly in Settings with the in-app fallback; dead subscriptions (404/410) are pruned.
- **AR8** A completed / deleted / paused / rescheduled entity has its pending reminders **cancelled** — verified by test, not assumed.

### C. Habits
- **AH1** Create with a name, frequency (daily or chosen weekdays), target count (+ unit), optional times and reminder, start/end date, "partial counts" on/off.
- **AH2** Logging is **absolute per local day** ("set today's count to 2"), so a retried tap can't double-log. States: *done* (count ≥ target) · *partial* · *skipped* (user's choice) · *missed* (derived, shown neutrally).
- **AH3** **Consistency %** (scheduled days in the last 14/30 where the target was met; partial credit if allowed) is the headline; the streak is secondary; missed days never use red or "failed" wording.
- **AH4** A habit reminder is skipped when the day's target is already met; habit reminders get no follow-ups.
- **AH5** A built-in habit **"English practice (DuSu)"** counts speaking minutes automatically from the database (no manual logging).
- **AH6** Targets are user-defined; no medical advice copy.

### D. Goals
- **AG1** Intake: goal, why, target date, minutes per day, what's done already, constraints.
- **AG2** AI drafts milestones + the first ≤ 14 days of tasks (schema-validated; ≤ 8 milestones, ≤ 30 tasks). The user reviews, edits and **approves** before anything becomes active; the draft is stored as a `proposed` version.
- **AG3** **Dates are computed by code**, never trusted from the model: per-day load ≤ the user's minutes, nothing after the target date, assumptions listed.
- **AG4** Today shows the *next actions*, not the whole roadmap; "Plan the next two weeks" produces the next batch on approval.
- **AG5** Progress is deterministic (§5.5) and shows **planned vs actual** ("on track" / "about 3 days behind").
- **AG6** Pause/resume (reminders stop/restart, history kept). Replan creates version n+1, shows a diff, needs approval, never rewrites history.
- **AG7** Goals work fully by hand; if the AI is unavailable the manual path is offered, never a dead end.

### E. Recovery
- **AE1** Trigger: ≥ 2 consecutive local days with a planned goal task unmet, or ≥ 3 overdue tasks → one **"Let's get back on track"** card (max once a day, dismissable, **never a push**).
- **AE2** Choices: *continue today's plan* · *reschedule unfinished work* (preview of new dates within the daily cap; approve) · *make it smaller* (AI split, or a deterministic "15-minute version").
- **AE3** Never auto-complete; never duplicate; keep original due dates and history; respect working hours and the daily cap; **ask before moving a milestone or goal deadline**.

### F. Dashboard & review
- **AF1** One **Today** screen: ≤ 3 priorities, due/overdue, habit strip, goals, due reminders, the recovery card.
- **AF2** Evening review (at the user's review time, or on open after 8 PM): counts, "what got in the way?" chips, "move unfinished to tomorrow" (approve). Skippable; never blocks the app.
- **AF3** Morning briefing is optional (D3).

### G. DuSu knowledge — see §10
- **AD1** With both switches on, DuSu answers "what's on my plate today?", "what's overdue?", "how's my lemon-water habit?" from the data, never claims to have created or changed anything, and doesn't nag.

### H. Settings & data rights
- **AS1** Timezone (auto + editable) · quiet hours · follow-ups · snooze default · briefing/review toggles · push on/off **with the live permission state** · hide-details toggle · **"Send me a test reminder"** · pause everything · **export JSON** · **delete all my planner data**.

---

## 3. Not in V1 (and why)

| Item | Why not now | When / guardrail |
|---|---|---|
| AWS shut-down automation | Needs AWS credentials; your spec forbids AI controlling infrastructure | V2: explicit connect, scoped IAM role, confirmation for anything destructive. V1 only *reminds* |
| Voice capture of tasks ("DuSu, remind me at 9") | Your spec: Version 2; needs a per-turn intent gate and a confirm card | V1.5 sketch in §10.4 |
| Calendar / availability-aware scheduling | Integration surface | V2 |
| Native Android alarms | TWA has no bridge; can't see user data | Not planned |
| iOS | D13 | — |
| XP / coins for tasks | D4 | Revisit after the pilot |
| Social, sharing, teams | — | — |
| Offline-first editing | Needs a sync/queue design, and the service worker deliberately never caches API data (per-user, shared-device safe) | V1 requires a connection and says so plainly when offline |

---

## 4. Screens & flows

**Entry points** (hidden until `userState.planner`): Home card **"My Day"** (live line: "3 tasks left · 2 of 3 habits"), More-sheet row, route `/my-day`. Inside the module a segmented top bar **Today · Tasks · Goals · Habits**, a 🔔 (Reminders) and ⚙ (Settings), and a floating **＋** that opens the Add sheet (Task / Habit / Goal / Reminder + a quick-add box). Each tab has its own route (`/my-day`, `/my-day/tasks`, `/my-day/goals`, `/my-day/habits`, `/my-day/reminders`, `/my-day/settings`) so Back/Forward work; all light up the More tab (`NAV_TAB`).

| Screen | Content | Notes |
|---|---|---|
| **Today** | greeting + counts · due reminder cards · ≤ 3 priorities · habit strip (tap-to-log glasses) · goals with progress and *next action* · recovery card · **Ask DuSu about my day** | one `GET /planner/today` |
| **Tasks** | chips *Today · Upcoming · Overdue · Done*; rows with a check circle, priority, time, goal chip, 💤 if snoozed | swipe-free (tap row → edit sheet) |
| **Goals** | goal cards (ring, "on track"); detail = milestones, next 14 days, versions, **Pause / Replan** | "New goal" stepper (§9.3) |
| **Habits** | today's progress, 14-day dots, consistency %, partial/skip | glasses UI is the spec's "Glass 1 / Glass 2" |
| **Reminders** | upcoming, snoozed, history; notification state | |
| **Settings** | AS1 | permission state is *read live* from the browser |
| **Add sheet** | quick-add: type or 🎤 → **preview card** with resolved dates in words ("Sat 11 Oct, 9:00 PM") → **Add / Edit / Dismiss**; manual forms below | AI optional; the preview is the approval step |
| **Reminder card** (in-app) | title, body, **Done · Later · Skip** (+ Reschedule) | same card for push and in-app |
| **Evening review** | counts, reason chips, "move unfinished to tomorrow", Skip | never modal-blocking |

**Copy rules.** No guilt ("you failed", "overdue!" in red). Missed = "Let's get back on track". Overdue is an amber chip, not red. Empty states invite ("Nothing planned — add one thing"). Wireframes: Appendix A.

**Accessibility & performance.** 44 px tap targets; every control has an accessible name; colour is never the only signal; `prefers-reduced-motion` respected; contrast checked on the navy/gold theme; one request paints Today; lists paged at 100.

---

## 5. Domain model

### 5.1 Tables (all new, prefix `pl_`; every row carries `user_id` and every query filters on it)

| Table | Key columns | Constraints / indexes |
|---|---|---|
| `pl_prefs` | `user_id` PK, `tz`, `quiet_on`, `quiet_start`, `quiet_end`, `followups`, `followup_gap_min`, `snooze_min`, `briefing_on/at`, `review_on/at`, `push_on`, `hide_details`, `work_from/to`, `daily_cap_min`, `paused_all`, `extra` JSONB | `tz` validated by `ZoneInfo` |
| `pl_goals` | `id`, `user_id`, `client_key`, `title`≤120, `why`≤500, `target_date`, `daily_minutes`, `status` active\|paused\|done\|archived, `plan_version`, `progress` (cached 0-100), `source` manual\|ai\|career, `created/updated/paused/completed/deleted_at` | `UNIQUE(user_id, client_key) WHERE client_key IS NOT NULL`; idx `(user_id, status)` |
| `pl_milestones` | `id`, `goal_id`, `user_id`, `seq`, `title`, `detail`, `due_date`, `status` open\|done\|skipped, `completed_at`, `version`, `deleted_at` | idx `(goal_id, seq)` |
| `pl_goal_versions` | `id`, `goal_id`, `user_id`, `version`, `status` proposed\|approved\|superseded\|discarded, `source` ai\|manual\|replan, `plan` JSONB (validated, dates resolved), `inputs` JSONB, `model`, `created_at`, `approved_at` | `UNIQUE(goal_id, version)` — the original AI plan is never overwritten |
| `pl_tasks` | `id`, `user_id`, `goal_id?`, `milestone_id?`, `parent_id?` + `occ_date?` (recurring series), `client_key`, `title`≤160, `notes`≤1000, `priority` 1-3, `due_date` (local), `due_has_time`, `due_at` (UTC; date-only = end of that local day), `orig_due_at`, `status` open\|done\|skipped, `completed_at`, `skipped_at`, `pin_date`, `recurrence` JSONB (template rows), `trigger` JSONB, `reschedules` JSONB (≤ 20), `tz`, `created/updated/deleted_at` | `UNIQUE(parent_id, occ_date) WHERE parent_id IS NOT NULL`; `UNIQUE(user_id, client_key) WHERE …`; idx `(user_id, status, due_at)`; overdue = `status='open' AND due_at < now()` |
| `pl_habits` | `id`, `user_id`, `client_key`, `title`≤100, `target_count`, `unit`, `partial_ok`, `schedule` JSONB (`days`, `times`, optional window), `start_date`, `end_date`, `status` active\|paused\|archived, `auto_source` null\|`dusu_minutes`, `goal_id?`, `deleted_at` | idx `(user_id, status)` |
| `pl_habit_logs` | `id`, `habit_id`, `user_id`, `day` (local date), `count`, `state` logged\|skipped, `note`≤200, `updated_at` | `UNIQUE(habit_id, day)` — absolute upsert |
| `pl_reminders` | `id`, `user_id`, `entity_type` task\|habit\|goal\|custom\|briefing\|review, `entity_id?`, `kind` time\|recurring\|condition, `title`, `body`, `occurrence_key`, `fire_at` (UTC), `tz`, `status` waiting\|scheduled\|sending\|sent\|done\|skipped\|expired\|cancelled, `attempts`, `followups_sent`, `snooze_count`, `push_state` none\|no_subscription\|accepted\|failed\|stale, `last_error`≤120, `claimed_at`, `sent_at`, `acted_at`, `action`, `created_at` | **`UNIQUE(occurrence_key)`**; partial idx `(fire_at) WHERE status='scheduled'`; idx `(user_id, status)` |
| `pl_push_subs` | `id`, `user_id`, `endpoint` (unique), `p256dh`, `auth`, `ua`, `created_at`, `last_ok_at`, `fail_count` | ≤ 5 per user (oldest dropped); pruned on 404/410 or `fail_count ≥ 5` |
| `pl_events` | `id`, `user_id`, `entity_type`, `entity_id`, `event_type`, `at`, `meta` JSONB (small) | idx `(user_id, at DESC)`; 180-day prune. Types: `created, completed, skipped, rescheduled, scheduled, deferred_quiet, push_attempt, push_accepted, push_failed, shown_inapp, acted, expired, ai_call, plan_approved, replanned, recovery_*, review_done` |

Timestamps are **UTC** (`timestamptz`); the user's IANA tz is stored alongside wherever local meaning matters. Soft-delete (`deleted_at`) on goals/tasks/habits; "delete all my data" hard-deletes everything (§11).

### 5.2 Task status (stored `open | done | skipped`; derived for display)

```
derive(task, now, tz):
  done/skipped            -> that
  open and due_at < now   -> overdue
  open and due_at <= now+3h -> due_soon
  open and its next reminder is `scheduled` after a snooze and not overdue -> upcoming + 💤 chip
  else                    -> upcoming
```
Transitions: `open → done` (complete) · `open → skipped` (skip) · `done|skipped → open` (reopen; recomputes progress) · reschedule changes `due_at` only (history appended) · delete = soft.

### 5.3 Reminder state machine

```
waiting ──trigger tapped / fallback time──▶ scheduled ──claim──▶ sending ──delivered──▶ sent ──act──▶ done | skipped
                                               ▲                    │                     │
                                               │ transient failure  │                     ├─ no act in `gap`, followups_sent < max ─▶ scheduled (same row, +1)
                                               └────backoff─────────┘                     └─ no act after the last follow-up ───────▶ expired  (task shows overdue)
 any state ──entity completed / deleted / paused / rescheduled──▶ cancelled        sent ──"Later"──▶ scheduled (fire_at = now + snooze, snooze_count+1)
```
Delivery state (`push_state`) is **separate** from lifecycle state, and both are separate from task completion (your spec §9 rule 4).

### 5.4 Time & recurrence
- `local_today(tz)`, `to_utc(local_date, local_time, tz)` via `zoneinfo`. **DST policy (documented and tested):** a nonexistent local time (spring-forward gap) resolves to the first valid instant after it; an ambiguous one (fall-back) fires **once**, at the earlier occurrence.
- Rule JSON: `{freq: daily|weekly|monthly, interval, byday:[0-6 Mon=0], bymonthday, time:"HH:MM"|null, until, count}`; "custom" = weekly + `byday`; day 31 clamps to month end. No `dateutil`.
- **Materializer** keeps a rolling **48 h** of concrete occurrences (recurring-task children, habit reminders, briefing/review) with `INSERT … ON CONFLICT DO NOTHING` on the unique key. Runs at boot, every 10 min, and immediately on create/edit.
- Changing timezone re-materializes future occurrences; past ones stay.

### 5.5 Formulas (deterministic, offline-testable)
- **Milestone fraction** = 1 if done; else `done_tasks / non-skipped tasks` (0 if none).
- **Goal progress** = `round(100 · Σ fractions / n_milestones)`, capped at 99 until the goal is marked done.
- **Expected progress** = elapsed days / total days (start → target). **Behind by N days** = `(expected − actual) · total_days`, shown only when ≥ 2.
- **Habit consistency** over a window = Σ over *scheduled* days of `min(1, count/target)` (or 1/0 if partial isn't allowed) ÷ scheduled days.
- **Workload** for a day = Σ `minutes` of open tasks due that day (tasks without minutes count 25).

---

## 6. Reminder engine

### 6.1 Loop (one asyncio task started from `startup`)
Every **15 s**, only when `planner != off`:
1. **Reclaim** — `sending` rows older than 2 min go back to `scheduled` (a crashed delivery).
2. **Claim** — `WITH c AS (SELECT id FROM pl_reminders WHERE status='scheduled' AND fire_at <= now() ORDER BY fire_at LIMIT 50 FOR UPDATE SKIP LOCKED) UPDATE … SET status='sending', claimed_at=now(), attempts=attempts+1 … RETURNING *`.
3. **Deliver** each (below), each in its own short transaction; one bad row never stops the rest.
4. **Follow-up pass** — `sent` rows with no action whose `sent_at + gap` has passed and `followups_sent < max` → `scheduled` again (same row); past the last gap → `expired`.
5. **Materialize** (every 10 min) and **prune** (daily).
The loop catches every exception, logs the class name only, and sleeps — it can never take the web server down.

### 6.2 Deliver(reminder)
1. Load the entity. Gone / done / skipped / paused / deleted, user blocked, planner off for that user, `paused_all` → **cancelled**, no send.
2. Habit already met for the day → **cancelled**.
3. **Quiet hours** (user's local clock): defer to the quiet end (`scheduled`, event `deferred_quiet`). No exceptions in V1 — predictable beats clever.
4. **Stale**: `now − fire_at > 120 min` (server was down) → `sent` with `push_state='stale'` — visible in-app, no push.
5. **Send**: in-app is simply the `sent` state (read by the app, §6.4). Push goes to every subscription in a worker thread (`pywebpush`, 8 s timeout, `TTL` 2 h, `Urgency: high`): 201 → `accepted`; **404/410 → delete that subscription**; 429/5xx/timeout → transient. All transient and none accepted → back to `scheduled` with backoff 30 s → 2 min → 10 min, up to 4 attempts, then `push_state='failed'` (still `sent`, still shown in-app).
6. Write events (`push_attempt`, `push_accepted|push_failed`).
"Delivered" never means "seen": a push service accepting a message is recorded as exactly that (your spec's warning).

### 6.3 Push action buttons without a login
A service worker can't read `localStorage`. Each push carries three single-purpose, signed, expiring tokens (done / later / skip): `base64url(rid|action|exp).HMAC` with a key derived from `SESSION_SECRET` for this purpose only, 24 h life, ≈ 60 bytes each. `POST /planner/r/act {t}` verifies, applies the action **idempotently**, and can do nothing else.

### 6.4 In-app channel
`GET /planner/due` (poll every 45 s while the app is visible, on `visibilitychange`, and when the service worker posts a message) returns reminders in `sent` (or `scheduled` and already due) that aren't acted on. The same card serves push and in-app; whichever action lands first wins. **If a DuSu window is visible, the service worker does not show a system notification — it posts a message instead** (no double alert).

### 6.5 Failure matrix

| Scenario | Behaviour |
|---|---|
| Server restarting / deploying (≈ 1 min) | Rows are in Postgres; on boot `reclaim` + the loop resumes; anything ≤ 120 min late still pushes, older = in-app only |
| Two loops (ever scaled) | `SKIP LOCKED` + unique `occurrence_key` → no double send |
| Push service down | Backoff, then in-app only; recorded as `failed`, counted in the admin card |
| Device offline at due time | FCM holds the message up to its TTL (2 h); else the in-app card is waiting on open |
| Permission revoked | Next send gets 404/410 → subscription deleted; Settings shows "off"; in-app continues |
| User deletes / completes / pauses mid-flight | `deliver` re-checks the entity at send time; also cancelled eagerly on the action |
| Clock/timezone change | Re-materialize; wall-clock times stay wall-clock |
| Same action tapped twice (push + app) | Idempotent: second call returns the current state, writes no event |
| A bad row (corrupt JSON, deleted FK) | Caught per row, marked `cancelled` with `last_error`, loop continues |
| Reminder storm (bug) | Per-user cap: ≤ 20 sends/hour; excess stay in-app, logged |

---

## 7. Channels & Android reality

### 7.1 Channels
| Channel | Works when | Notes |
|---|---|---|
| **In-app** | the app is open | always on; this is the guaranteed path |
| **Web Push (VAPID)** | permission granted and the browser/OS lets Chrome run in the background | payload encrypted end-to-end (RFC 8291); the push service sees metadata only |
| Native Android alarm | — | not used (no bridge; can't see tasks) |

**VAPID keys:** `VAPID_PRIVATE_KEY` / `VAPID_PUBLIC_KEY` from the environment if set; otherwise generated once and stored in the `settings` table (a P-256 key fits the 255-char column), so a container rebuild never invalidates subscriptions. No `.env` edit needed. If `pywebpush` can't import, push disables itself and the module runs in-app only (import gate stays green).

### 7.2 Compatibility matrix (your spec's 8 scenarios × how DuSu is opened) — **all cells except N1 are UNVERIFIED**

| # | Scenario | Chrome tab | Installed PWA | TWA from Play | Sideloaded APK |
|---|---|---|---|---|---|
| N1 | App open, foreground | in-app card (by design) | same | same | same |
| N2 | App in background | to verify | to verify | to verify | to verify |
| N3 | Browser/app closed / swiped away | to verify | to verify | to verify | to verify |
| N4 | Device offline at due time | to verify (FCM TTL) | | | |
| N5 | Back online after a missed reminder | to verify (≤ 120 min push, else in-app) | | | |
| N6 | Permission denied / revoked | to verify UX | | | |
| N7 | Device restarted | to verify | | | |
| N8 | Rescheduled across midnight | server logic is unit-tested; one live run | | | |
| — | Battery saver / OEM task killers (Xiaomi, Oppo, Vivo, Realme…) | **the biggest unknown for a budget-Android audience** | | | |

Nothing is promised to users until a cell is filled with a result. Settings gets **"Send me a test reminder"** (schedules one 60 s out) so the owner can run N2–N7 in minutes on a real phone.

### 7.3 If push doesn't work inside the installed app
Decision order: (1) read the android-browser-helper docs for **notification delegation** (`DelegationService` + manifest entries — I could not confirm the exact entries from a search, so this is read at implementation time) and ship a new AAB/APK with it enabled — note this touches the Play closed test, so it needs its own plan; (2) otherwise tell Android users to also install DuSu as a Chrome PWA for background reminders; (3) otherwise in-app only, with honest copy. Server-side work is identical in all three.

---

## 8. API contract

Prefix `/planner`. **Gate** (`_planner_gate`, same shape as `_practice_gate`): valid session (Bearer or `token`) → `planner_enabled(email)` else **404** → not blocked else **403** → *(AI endpoints only)* `resolve_keys` else **402 `keys_required`**; quota → 429; provider failure → 502. Every row access is `WHERE user_id = :uid`; an id that isn't yours returns **404** (never 403, so ids can't be probed). Create endpoints accept `client_key` (idempotency). Bodies are validated and clamped server-side; the client is never trusted for status, ownership or dates.

| Method · path | Purpose | Notes |
|---|---|---|
| GET `/today` | dashboard payload | priorities, due, habits, goals, reminders, recovery, review |
| GET `/tasks?view=today\|upcoming\|overdue\|done&goal_id=` | list | ≤ 100 |
| POST `/tasks` | create | `client_key`; may include `remind`, `trigger`, `recurrence` |
| PATCH `/tasks/{id}` | edit | |
| POST `/tasks/{id}/complete` · `/reopen` · `/skip` | status changes | idempotent |
| POST `/tasks/{id}/reschedule` | `{due_date, due_time, reason}` | keeps history |
| POST `/tasks/{id}/pin` | `{on}` | ≤ 3 per day |
| POST `/tasks/{id}/trigger` | fire a condition task | idempotent |
| DELETE `/tasks/{id}` | soft delete | cancels reminders |
| GET `/habits` · POST `/habits` · PATCH `/habits/{id}` · DELETE `/habits/{id}` | CRUD + today/14-day/consistency | |
| PUT `/habits/{id}/log` | `{day, count \| skipped}` | **absolute**, idempotent |
| GET `/goals` · POST `/goals` · GET `/goals/{id}` · PATCH `/goals/{id}` | CRUD, pause/resume/done/archive | |
| POST `/goals/draft` | **AI** intake → proposed version | not active yet |
| POST `/goals/{id}/approve` | `{version, edits}` | creates milestones + first batch |
| POST `/goals/{id}/replan` · `/next-batch` | **AI** revised version / next 2 weeks | diff shown, approval required |
| POST `/parse` | **AI** sentence → draft items + at most one question | |
| POST `/tasks/{id}/split` | **AI** 2-4 smaller steps | |
| GET `/due` | in-app reminder cards | polled |
| GET `/reminders?view=upcoming\|history` · POST `/reminders` | list · custom reminder | |
| POST `/reminders/{id}/act` | `{action: done\|later\|skip\|reschedule, minutes?, to?}` | idempotent |
| POST `/r/act` | `{t}` — **token-authenticated** (service worker) | no session; single-purpose token; **still 404 when the switch is off** |
| GET `/recovery` · POST `/recovery/apply` | detect + proposals · apply `{choice, ids}` | preview first |
| GET `/review` · POST `/review` | evening review · `{reasons, carry:[ids]}` | |
| GET/PUT `/prefs` | settings | tz validated |
| GET `/push/key` · POST/DELETE `/push/subscribe` · POST `/push/test` | push management · test reminder | |
| GET `/export` · POST `/delete-all` | data rights | |
| `/me` | adds `planner` (bool for this user) | |
| `/admin/overview` · `/admin/settings` | add `planner` mode + health card · `planner` switch | owner only |

Rate limits: AI 20/day/user; creates 100/day/user (system-generated recurrences excluded); `/r/act` 60/min/IP.

---

## 9. AI design

### 9.1 Who does what
| AI may | Code must |
|---|---|
| Understand a sentence / a goal | Validate and save it |
| Propose milestones, tasks, priorities, smaller steps | Compute every date; enforce per-day load, deadlines, limits; assign ids |
| Explain what changed in a replan | Version it, diff it, require approval |
| — | Complete tasks, move deadlines, send reminders, touch AWS — **never** via the model |

### 9.2 Calls (all `llm.assess(system, payload, temperature=0.2)`; JSON repaired by `_extract_json`; one automatic retry on schema failure; user text is wrapped as *data*, never as instructions)
1. **`parse`** — text + local now + weekday + tz → `{items:[{type, title, due_date, due_time, priority, repeat, remind, remind_time, trigger{type,label,fallback_time}, habit{target,unit,times}, notes, confidence}], question}`, where `type` ∈ task\|habit\|goal\|reminder and `remind` ∈ `at_due`\|`before_15`\|`before_60`\|`at_time`\|`at_trigger`\|`none`. Server checks dates (not > 1 day in the past, ≤ 2 years ahead) and the preview card shows them **in words** — that is the safety net for date mistakes.
2. **`goal_draft`** — intake → `{summary, milestones:[{title, detail, end_day}], first_tasks:[{title, minutes, day, milestone, priority}], assumptions[], risks[]}`. `day`/`end_day` are **offsets from the start day**; the server turns them into dates.
3. **`replan`** — intake + a progress snapshot + the user's reason chips → same schema + `changes[]`.
4. **`split`** — task + minutes → `{steps:[{title, minutes}]}` (2-4).

Validation: ≤ 8 milestones, ≤ 30 tasks, 5 ≤ minutes ≤ 240, offsets monotonic and ≤ the target, titles ≤ 120 chars, unknown keys dropped. Failure → "I couldn't draft that — try again or add it by hand." (AG7.)

### 9.3 Goal flow
Stepper: **Goal → Why → Deadline → Minutes/day → Already done → Constraints** → "Draft my plan" → review sheet (milestones, the first two weeks, assumptions; edit/remove any line) → **Approve** (creates milestones + tasks) or **Discard**. Only the first ≤ 14 days become tasks; "Plan the next two weeks" repeats the loop. Replan shows *moved / added / removed / re-scoped* lines and needs approval.

### 9.4 Prompt injection & cost
Titles, notes and goal text are the user's own data and only ever go into *their own* prompts. AI runs only on an explicit tap (never in the background), BYOK-gated, 20/day, so it can't drain the free shared quota. Worked example (your AWS case) in Appendix B.

---

## 10. DuSu integration

### 10.1 DuSu knows the plan (Part 1's hook)
`life.EXTRA_LINES.append(planner_lines)` — registered at import. `planner_lines(uid)` returns ≤ 4 short lines, built from live rows, titles flattened to one quote-safe line:
- `Today's plan: 3 tasks open (pinned: Finish trading research; Product work 45 min), 1 overdue (Pay rent, 2 days).`
- `Habits today: Lemon water 1 of 2 glasses; English practice 8 of 15 min.`
- `Goals: Launch my product - 34%, about on track; next milestone 'Finish MVP spec' due 14 Oct.`
- `Next reminder: 9:00 PM - Check and shut down AWS.`
- plus the rule: `You cannot change their tasks from a conversation yet. If they ask you to add or change one, tell them to tap + in My Day; never say you have set a reminder.`

Two small changes in Part 1's code when this lands: `EXTRA_LINES` callables get `(uid, email)` so the provider can check `planner_enabled(email)`, and `life.build` passes the email. DuSu mentions the plan only when **both** switches (`life_context` and `planner`) are on for that learner.

### 10.2 "Ask DuSu about my day"
A button on Today opens Face-to-Face Talk with a seed line ("What's on my plate today?") through the existing Companion-Moment `seed` — DuSu answers from the numbers + plan lines. No new voice plumbing.

### 10.3 Memory
On a milestone completed or a habit's 7-day consistency, add an **achievement** line via the existing `_add_achievements` ("Finished 'MVP spec' toward Launch my product") so the companion can celebrate it later. No XP (D4).

### 10.4 V1.5 sketch — voice capture
A keyword gate (English + Hinglish: "remind me", "yaad dila", "add task", "reminder") on conversation `user_text` triggers `parse` in the background; the WebSocket sends a `planner_draft` frame; the client shows the **same preview card** (Add / Edit / Dismiss). DuSu's spoken reply stays normal. Nothing is saved without a tap.

---

## 11. Privacy, security & data rights

| Topic | Decision |
|---|---|
| Data stored | tasks, notes, goals, habits, reminders, prefs, push subscriptions (endpoint + keys), events. Same Postgres as everything else. Not stored: AWS or any third-party credentials — ever |
| Isolation | every query has `user_id = :uid`; foreign ids → 404; **an IDOR test hits every endpoint with a second user's ids** (§12) |
| Push | payload encrypted to the device's keys; lock-screen text controlled by D6; the push endpoint is a device identifier (declare it) |
| Action tokens | per-reminder, per-action, 24 h, HMAC with a purpose-derived key; can only perform that action |
| Logging | class names only; never titles, notes or goal text (same rule as `_safe_err`) |
| AI | no tool use; output validated; user text as data; keys stay BYOK |
| Rights | **Export** = JSON of every planner table for that user; **Delete all** = hard delete + subscriptions revoked; **Pause everything** keeps data but stops reminders; account deletion (`delete_user`) and the owner wipe (`admin_wipe_users`) get the new tables added to their explicit lists (a forgotten table there = orphaned personal data) |
| Docs | `privacy.html`, `terms.html`, `account-deletion.html` updated **before** the switch goes beyond *owner*; **Play Data-safety** to be re-answered (user-generated content; device/push identifier) — same gate as the Practice Room's audio |
| Abuse | limits in D9; `/r/act` rate-limited; per-user send cap 20/h |

---

## 12. Verification plan

I follow the repo's standing rule (no test suites in the repo; scratch scripts; verify the real thing) — if you *do* want tests committed under `tests/`, say so.

| Tier | What | Where |
|---|---|---|
| **1 Pure logic** | recurrence, DST gap/overlap, quiet-hour deferral, status derivation, progress/consistency/behind-by, per-day load balancing, AI-output validators fed **canned** (including hostile) model outputs, action-token sign/verify/expiry | offline, venv — no DB |
| **2 Server on a scratch Postgres** | old→new migration; every endpoint through the real HTTP layer; **two-user IDOR matrix over every endpoint**; idempotency (double complete, double act, double create with the same `client_key`); the scheduler against a **fake push sender** with a fake clock; **kill the loop mid-delivery and restart** (no loss, no duplicate); transient-failure backoff; quiet hours; follow-ups then `expired`; deleted/paused entities cancel reminders; export/delete-all/`delete_user` leave nothing behind | host, scratch DB only |
| **3 Browser look** | the real client in Chromium with stubbed endpoints: each screen, Add sheet + preview, reminder card, empty/error states, 360 px and desktop, reduced motion, computed-style checks against the global-CSS collision trap, the permission-state UI | Playwright harness |
| **4 Real model** | 20 prompts (English / Hindi / Hinglish, incl. your AWS example and the 90-day launch) through `parse` / `goal_draft` / `replan` / `split`; judged for schema validity and date correctness | host, paced (free Gemini 429s on bursts) |
| **5 Owner's phone** | §7.2 matrix on Chrome tab / PWA / Play TWA / sideloaded APK, on the owner's actual handset(s); a day of real use | **cannot be done without you** |

Your spec's 17-item release checklist → tier: create/edit/complete/reschedule **2+3** · overdue survives reload **2+3** · completing cancels the reminder **2** · no duplicate completion **2** · fires at the right local time **1+2, then 5** · works when closed **5** · restart loses nothing **2 + the live deploy** · snooze doesn't duplicate **2** · revoked permission **3+5** · recurring habits dated correctly **1+2** · partial log **1+2** · goal progress from tasks **1+2** · replan keeps history & needs approval **2+4** · DST **1** · one user can't read another's **2** · retries don't duplicate **2** · deleted/paused don't fire **2**.

**Honest limits:** tiers 1-4 can fully pass and push-when-closed can still fail on a real handset. That is why P2 ends with tier 5 before P3 starts.

---

## 13. Phases & tickets

Every phase ends deployed **dark** (switch off → zero behaviour change, checked on the live site), with its own exit criteria.

### P0 — Foundations (S)
| ID | Ticket | Files | Dep |
|---|---|---|---|
| PL-0.1 | `pywebpush==1.14.1`, `tzdata` in requirements; import check in the container | `requirements.txt` | — |
| PL-0.2 | package skeleton; `planner_mode()` / `planner_enabled()`; `/me.planner`; dashboard select; overview stub | `planner/__init__.py`, `main.py`, `test_client.html` | — |
| PL-0.3 | `timeutil.py` (tz, recurrence, DST) + `rules.py` (status, progress, limits) + tier-1 checks | `planner/timeutil.py`, `rules.py` | — |
| PL-0.4 | models + `init_db` indexes (explicit partial unique indexes) + migration check on a scratch DB | `planner/models.py`, `db.py` | 0.2 |
| PL-0.5 | add the tables to `delete_user` / `admin_wipe_users`; export skeleton | `db.py`, `planner/service.py` | 0.4 |

**Exit:** flag off, live site byte-identical in behaviour; migration clean on the old schema; tier-1 green.

### P1 — Tasks, goals by hand, Today, DuSu knows (L)
| ID | Ticket | Dep |
|---|---|---|
| PL-1.1 | task service: create/edit/complete/skip/reopen/reschedule/pin/delete, derived status, ownership, idempotency, events, limits | P0 |
| PL-1.2 | goals + milestones CRUD, progress, pause/resume/archive | P0 |
| PL-1.3 | `/planner/today`, `/tasks`, `/goals` endpoints + gate | 1.1, 1.2 |
| PL-1.4 | client `PL` module: routes, Home card, More row, ＋ Add sheet (manual forms), Today, Tasks, Goals; `pl-` CSS | 1.3 |
| PL-1.5 | life-lines provider + "Ask DuSu about my day" | 1.3, Part 1 |
| PL-1.6 | "due now / overdue" banner on Today computed from tasks (no reminder rows yet) | 1.4 |

**Exit:** you can plan a day by hand; DuSu answers "what's on my plate?" correctly (tier 4 + a real chat); tier 2 IDOR matrix green.

### P2 — Reminders (L — *the critical dependency*)
| ID | Ticket | Dep |
|---|---|---|
| PL-2.1 | reminder rows from tasks (at due / before / custom), eager cancel + resync on change | P1 |
| PL-2.2 | scheduler loop: claim, deliver, quiet hours, stale, backoff, follow-ups, expire, reclaim, prune; admin health | 2.1 |
| PL-2.3 | push: VAPID in settings, subscribe/unsubscribe/test, service-worker `push` + `notificationclick` + action buttons + visible-window suppression, signed action tokens + `/planner/r/act` | 2.2 |
| PL-2.4 | `/due` + act endpoints; in-app reminder cards; Settings screen with the live permission state and **Send me a test reminder** | 2.2, 2.3 |
| PL-2.5 | condition tasks (**▶ trigger** chip + fallback time) | 2.1 |
| PL-2.6 | **tier-5 phone matrix** (you) → decide §7.3; record results in this file | 2.4 |

**Exit:** §7.2 matrix filled for your phone(s); tier 2 "kill and restart" green; **stop and decide** before P3.

### P3 — Habits & recurring tasks (M)
PL-3.1 habits + logs + consistency + schedule + habit reminders (skip-if-met) · PL-3.2 Habits screen (tap-to-log glasses, dots, partial/skip) + Today strip · PL-3.3 auto-source "English practice (DuSu)" from `daily_stats` · PL-3.4 recurring tasks (series templates + materializer + unique `(parent_id, occ_date)`). **Exit:** DST and recurrence checks green; a week of dated occurrences correct.

### P4 — AI planner (M)
PL-4.1 prompts, schemas, validators, day-offset → date scheduler (tier 1 with canned outputs) · PL-4.2 `/parse` + quick-add preview (+ mic via the existing recogniser) · PL-4.3 goal draft → review → approve, versions, stepper UI · PL-4.4 replan, next-batch, split · PL-4.5 Career Roadmap stage → "Make this a goal". **Exit:** tier-4 prompt set passes; BYOK gating verified.

### P5 — Recovery & review (M)
PL-5.1 missed detection + `/recovery` + apply (3 options, history kept) · PL-5.2 evening review + optional briefing/review pushes · PL-5.3 workload balancer (daily cap, working hours). **Exit:** scripted "miss two days" scenario end to end.

### P6 — Polish & rollout (M)
PL-6.1 accessibility pass · PL-6.2 export/delete UI + privacy/terms/account-deletion + Play Data-safety · PL-6.3 admin metrics card · PL-6.4 full checklist run, **≥ 7-day owner-only soak**, then `on` · PL-6.5 CLAUDE.md §11 + memory notes.

**Rough size:** P0 ≈ 5% · P1 ≈ 25% · P2 ≈ 25% · P3 ≈ 12% · P4 ≈ 15% · P5 ≈ 10% · P6 ≈ 8%.

### Files (new unless noted)
`backend/app/planner/{__init__,models,timeutil,rules,service,scheduler,push,ai,api,life_lines}.py` · `backend/app/interview/prompts.py` (4 prompts) · edits: `main.py` (include router, flag, startup hook, `/me`, admin), `db.py` (delete hooks, indexes), `life.py` (the `(uid, email)` tweak), `sw.js`, `test_client.html`, `requirements.txt`, `privacy/terms/account-deletion.html`, `CLAUDE.md`. Pure modules (`timeutil`, `rules`) have no DB imports so tier 1 can run without one.

---

## 14. Rollout & metrics

**Stages:** deploy dark → `owner` (a week of real use on your phone, plus the matrix) → decide `on` (or add a tiny tester table if you want a cohort, D2) → `on`. **Rollback = switch off**: the scheduler idles, data stays, pushes stop immediately. Don't surface it to the closed-test testers mid-test without a plan (same rule as the Practice Room).

**Metrics** (from `pl_events`; admin card; **no numeric targets until the pilot gives a baseline**, per your spec):

| Metric | Source |
|---|---|
| Task completion rate · on-time completion rate | `created` vs `completed` vs `due_at` |
| Reminder action rate | `acted` ÷ `sent` (push and in-app separately) |
| Habit consistency | `pl_habit_logs` |
| Goal milestone completion | `pl_milestones` |
| Recovery rate | tasks completed within 3 days of a `recovery_*` event |
| Notification failure rate | `push_failed` ÷ `push_attempt` |
| Week-four retention | users with any planner event in week 4 after their first |
| Queue health | oldest `scheduled` row overdue by > 2 min; `failed` count; stuck `sending` |

---

## 15. Risks & open questions

| # | Risk | Likelihood / impact | Mitigation |
|---|---|---|---|
| R1 | Push doesn't survive closure inside the TWA, or OEM battery killers drop it | **High / High** | in-app is the guaranteed path; test button; §7.3 fallbacks; nothing promised until the matrix is filled |
| R2 | Size (≈ 5–6k lines) | High / Med | phase gates; P0–P2 first; each phase ships dark |
| R3 | The model gets a date wrong | Med / Med | code computes dates; the preview shows them in words; approval before saving |
| R4 | Free-LLM quota / Gemini-lite JSON glitches (~1 in 9) | Med / Low | AI on explicit tap only; repair + one retry; manual path always |
| R5 | Notification fatigue | Med / Med | D3 defaults; caps; no follow-ups for habits; briefing/review opt-in |
| R6 | Deploy gaps (≈ 1 min) | Low / Low | reclaim + 120-min catch-up policy |
| R7 | Client file collisions (unscoped CSS) | Med / Low | `pl-` prefix; computed-style checks |
| R8 | Play policy / Data-safety mismatch | Med / High | privacy pages + form updated before anything beyond *owner* |
| R9 | Travel / timezone changes | Low / Low | banner "your device timezone changed — update?" |
| R10 | Collides with the Play closed test | Med / Med | dark by default; no tester exposure without a plan |

### Questions for you (my default in bold — silence = default)
1. **Go for P0–P2 now**, or all phases?
2. Name/placement: **"My Day", Home card + More row** — or a bottom-nav tab?
3. A **tester cohort** before "everyone"? (needs a tiny table) — default: owner → on.
4. Notification defaults as D3? (**yes**)
5. Any wish for tasks to earn XP? (**no**, D4)
6. Voice capture right after P2 (**V1.5**) or later?
7. Which phone model(s) will run the §7.2 matrix? (brand and Android version matter for battery killers)
8. Condition reminders: keep the **fallback time** (D14)?

---

## Appendix A — wireframes (mobile, 360 px)

```
TODAY                                      REMINDER CARD (in-app = push)
┌──────────────────────────────────┐       ┌──────────────────────────────┐
│ My Day              Sat 10 Oct 🔔⚙│       │ DUSU · IMPORTANT TASK        │
│ [Today] Tasks  Goals  Habits     │       │ Have you shut down your AWS  │
├──────────────────────────────────┤       │ server?                      │
│ Good evening, Asha               │       │ Check it before you end the  │
│ 3 tasks left · 2 of 3 habits     │       │ day.                         │
│ ┌ REMINDER · 9:00 PM ──────────┐ │       │ [✓ Done] [⏰ Later] [Skip]    │
│ │ Have you shut down AWS?      │ │       └──────────────────────────────┘
│ │ [✓ Done] [⏰ Later] [Skip]    │ │
│ └──────────────────────────────┘ │       ADD (＋) — quick add + preview
│ Today's priorities               │       ┌──────────────────────────────┐
│ ◯ Finish trading research  High  │       │ Type or 🎤:                  │
│ ◯ Check & shut down AWS   ▶ when │       │ "after trading remind me to  │
│     Trading finished             │       │  shut down aws"              │
│ ◯ Product work · 45 min  🎯 Launch│      │ ┌ I understood ────────────┐ │
│ Habits                           │       │ │ Task: Shut down AWS      │ │
│ 🍋 Lemon water   (●)(○)  1/2     │       │ │ When: after you tap      │ │
│ 🗣 English (DuSu) 8 / 15 min     │       │ │  "Trading finished"      │ │
│ Goals                            │       │ │ Or at: 9:30 PM (fallback)│ │
│ Launch my product ▓▓▓░░░ 34%     │       │ └ [Add] [Edit] [Dismiss] ──┘ │
│  next: Finish MVP spec · 14 Oct  │       └──────────────────────────────┘
│ [ Ask DuSu about my day ]   (＋) │
└──────────────────────────────────┘

RECOVERY (never a push)                    GOAL DRAFT REVIEW
┌──────────────────────────────────┐       ┌──────────────────────────────┐
│ Let's get back on track          │       │ Launch my product · 90 days  │
│ You missed two planned work      │       │ 1  Define     (to 24 Oct) ✎ ✕│
│ sessions. What would help?       │       │ 2  Build      (to 22 Nov) ✎ ✕│
│ ( ) Continue with today's plan   │       │ 3  Validate   (to 15 Dec) ✎ ✕│
│ ( ) Move unfinished work (preview)│      │ 4  Launch     (to 08 Jan) ✎ ✕│
│ ( ) Make it smaller              │       │ First two weeks: 12 tasks    │
│ [Continue]            [Not now]  │       │ Assumes 45 min/day · …       │
└──────────────────────────────────┘       │ [Approve plan] [Discard]     │
                                           └──────────────────────────────┘
```

## Appendix B — your AWS example, end to end (what the model returns vs. what code does)

Input: *"After I finish my trading research, remind me to shut down my AWS server."*

Model (`parse`) → `{items:[{type:"task", title:"Check and shut down AWS server", priority:"high", trigger:{type:"manual", label:"Trading finished", fallback_time:null}, remind:"at_trigger", notes:"Make sure the server isn't left running."}], question:"Should I remind you anyway at a fixed time if you forget to tap?"}`.
Code: validates, shows the preview card, asks the one question, saves on **Add**, creates a `waiting` reminder. Tap **▶ Trading finished** → `trigger` → `scheduled` now → push/in-app "Have you shut down your AWS server?" → **Done / Later / Skip**. If a fallback time was chosen it schedules itself then. Nothing ever talks to AWS.

## Appendix C — push payload (≈ 700 bytes of the 4 KB limit)

`{"title":"DuSu · Important task","body":"Have you shut down your AWS server?","tag":"t123:0","data":{"rid":456,"url":"/my-day?r=456","act":{"done":"…","later":"…","skip":"…"}},"actions":[{"action":"done","title":"Done"},{"action":"later","title":"Later"},{"action":"skip","title":"Skip"}]}` — with D6 on, title/body become "You have a reminder".

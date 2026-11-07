# DuSu — Project Guide (CLAUDE.md)

> **⚠️ 2026-09-20 — the database is now SELF-HOSTED.** DuSu runs on the `db` Postgres
> service in this repo's `docker-compose.yml`; the managed **Neon** database was retired and
> all its data migrated across. Compose builds `DATABASE_URL` from the `POSTGRES_*` vars in
> the root `.env` and injects it into the backend, overriding `backend/.env` — so the app
> structurally cannot reach an external provider. Every "Neon" mention below this line is
> historical. Bring the stack up with `docker compose up -d` (that is the PRODUCTION run;
> for a hot-reload dev loop add `-f docker-compose.yml -f docker-compose.dev.yml`).

> **⚠️ 2026-10-27 — the AI-key layer was rebuilt (section 19) and the web app became installable (section 20).**
> The LLM chain is now **groq → gemini → openrouter** (GitHub Models was removed: it answers `200 "OK"` to any
> token, so it could neither validate a key nor serve a reply) with the models listed in `config.py`; keys are
> judged **per key** (`backend/app/keys/`), counted in a usage ledger, saved by merge on the server (the stored key
> wins) and explained to the learner in plain words. Every older line below that says "gemini → groq → openrouter
> → github", `dusu-v5` (the service-worker cache is `dusu-v35`), "the Keys page reads `localStorage`", or
> `set_active_keys(keys)` with one argument, is historical — **sections 18, 19 and 20 are authoritative**.

> **⚠️ 2026-10-28 — a locked screen no longer kills a voice chat (section 21).** Before, "the page is hidden" ran `stopAllVoice()` (recogniser dropped, `running = false`,
> socket closed and nulled) and nothing handled the return, so the 🎤 and Reply stayed dead until the chat ended. Now `VP` (in `backend/test_client.html`) PAUSES every voice chat - Daily Talk,
> Learn, Face-to-Face, Interview, the Practice Room's conversations and the Home chat - checks the socket on return and reconnects quietly if it died (`start {reconnect:true}` ->
> `daily_resumed` / `session_resumed`); `ping` -> `pong` was added to the WebSocket. Every older line that says "hidden -> `stopAllVoice()`" is historical.

> **⚠️ 2026-10-30 — "AI busy" (section 22; DEPLOYED 2026-10-30).** The owner's screenshot of "AI busy - your keys are fine" turned out to hide a real fault: **DuSu's OWN AI keys were nearly all dead** - Groq rejected (401), Gemini **403 "The Gemini API free tier is not available for this project"** on every chat call (while `GET /models` and so `/health` said ok), OpenRouter's free pool busy. A failed turn is now ONE calm bottom pop-up with an honest countdown, ONE automatic retry that sends the same words and a button (never the top banner or an English line in the chat); the server no longer mislabels a busy provider as "your keys hit their limit"; `/health` sees a key that lists models but cannot chat. **The owner must still replace the Gemini and Groq keys in `backend/.env`** (steps in section 22).

> **⚠️ 2026-10-30 (night) — the product/UI audit fixes (section 23; DEPLOYED 2026-10-31 - image 301a73d4ebf6 is live; one small follow-up build, d57621b7ea9f, is tested and waits for the owner's go-ahead).** Every item of `DUSU_PRODUCT_UI_AUDIT_2026-10-30.md` now has a status in `DUSU_AUDIT_FIX_PLAN.md`: a first-run Keys wizard, Reserve-my-plan, first-run counters + an owner funnel, a first visit of ~430 KB instead of ~2.9 MB, a shorter Home, one name per feature, lining numerals, nothing under 12 px, 44 px targets, a slim header, and XSS hardening. **The independent review found a bug that is LIVE in production today** (the Home keys card re-asks a failing `/keys/status` in a tight loop - 1,423 requests in 6 s measured against the deployed page); it is fixed and live since 2026-10-31. **2026-10-31 - a fresh-eyes visual review of the final screens found 20 things (15 fixed or partly fixed, 4 left to the owner, 1 taste item; triaging them also surfaced a decorative-settings finding for the owner) and one more bug that is LIVE in production: every learner who practised yesterday sees yesterday's session count as "today's" every morning, and a dead streak stays "alive" (the stored counters only change on the next practice) - fixed and live since 2026-10-31 (`db._live_counters`, section 23).**

> **⚠️ 2026-11-07 — source control.** Everything through section 23 (the AI-busy fixes, the audit batch and the not-yet-live build 3) is committed on branch `fix/voice-screen-lock` (it contains `feat/keys-install-notify`) and pushed to `origin` = `git@github.com:Me-Bro/DuSu.git` (a PUBLIC repo; the repo URL in "Read me first" below is older). `main` and `origin/main` are still at `057e58c` - nothing is merged. Production runs image `301a73d4ebf6` (build 2); `dusu-backend:latest` is build 3 (`d57621b7ea9f`) and is NOT running. Older lines below that say "local, not pushed" or "not committed" describe the day they were written.

> **Read me first.** This is the single onboarding doc for a fresh Claude Code session (e.g. after moving the repo to another laptop). It explains the whole product, architecture, backend, frontend, database, LLM, mobile apps, Cloudflare plan, and dev/deploy workflow. Repo: `git@github.com:davidrana123/dusu-app.git`. Live: <https://dusu-app-1.onrender.com>. Also note: run the backend from `backend/.venv`; secrets live in `backend/.env` (**never commit**); Render **auto-deploys on push to `main`**.

## Table of Contents

1. [Product Overview](#1-product-overview)
2. [Architecture & Repo Layout](#2-architecture--repo-layout)
3. [Backend API (`backend/app/main.py`)](#3-backend-api-backendappmainpy)
4. [Database (backend/app/db.py)](#4-database-backendappdbpy)
5. [LLM Brain, Providers & Prompts](#5-llm-brain-providers--prompts)
6. [Frontend — Shell, Auth & Routing (backend/test_client.html)](#6-frontend--shell-auth--routing-backendtest_clienthtml)
7. [Frontend — Flows & Screens (backend/test_client.html)](#7-frontend--flows--screens-backendtest_clienthtml)
8. [Mobile Apps, Cloudflare, Deploy & Dev/Ops](#8-mobile-apps-cloudflare-deploy--devops)

---

## 1. Product Overview

### What DuSu is

**DuSu** is a **voice-first AI English-speaking coach** — tagline **"Speak with Confidence."** The user talks out loud; DuSu listens (browser speech-to-text), thinks (an LLM), and replies with a spoken voice (browser text-to-speech). It is deliberately positioned as a **companion, not a lesson app** — a warm mentor who remembers you, notices your mood, and holds ONE ongoing relationship across all practice modes. There are no grammar drills or flashcards; the product trains the thing people actually freeze on: *speaking to another human under pressure*.

The app ships as a **single-file web app** (`backend/test_client.html`, ~4,200 lines of vanilla HTML/JS/CSS — no build step) served by a **FastAPI** backend (`backend/app/`). Speech never leaves the browser; the WebSocket wire carries **text only**. It is installable as a **PWA** (`manifest.webmanifest` + `sw.js`) and wrapped as an Android **TWA/APK** (`android-twa/`, older `android-launcher/`; shipped artifacts `DuSu-app.apk`, `DuSu.apk` at repo root).

- Live URL referenced throughout the code: `https://dusu-app-1.onrender.com` (Render). Planned custom domain: `dusu.ranabrothers.online` (Cloudflare, not yet cut over).
- Cost model: **$0 running cost** — free LLM tiers + free browser speech.

### Target users

Indian, **mobile-first, budget-Android** learners who *know* some English but freeze when they must speak it — freshers/students prepping for **job interviews and campus placements**, non-metro/non-native speakers wanting low-pressure practice, and anyone building **daily speaking confidence**. Primary wedge: **India — freshers + placement season.** The icon/brand brief explicitly targets "budget Android, aspirational (job / interview / daily confidence)."

### The companion / emotional angle

This is the product's core differentiator, implemented in real code (not just planned):

- **Persistent emotional memory** — a per-user JSONB `memory.facts` doc stores nickname, profession, dream, interests, `facts_learned`, `moments` (time-boxed life events with an emotion, 2–7 day shelf life via `_prune_moments`), `achievements`, `energy_today`, `next_hook` (a promise to continue next time), `daily_context`, and `recent_turns` (raw tail of the last chat for **cross-mode continuity**).
- **Relationship Journey (internal, never shown)** — `relationship_stage()` promotes the user through 6 stages based on days + session count: **Guest → Friend → Practice Partner → Coach → Mentor → Companion** (`_REL_STAGES`). Each stage injects a different tone into DuSu's system prompt (`_STAGE_TONE` in `main.py`).
- **Companion Moment** — on Start Speaking, DuSu speaks *first* from memory. `POST /greeting` generates a warm **Hinglish** greeting (Devanagari for Hindi words so TTS pronounces them naturally) via `GREETING_SYSTEM`.
- **Weekly letter** — `POST /letter` generates a personal mentor note at most once every 7 days (needs xp ≥ 20), via `LETTER_SYSTEM`.
- Session end runs ONE combined LLM pass (`summarize_and_extract` → `SESSION_MEMORY_SYSTEM`) that writes a summary, merges facts/events, sets the next hook, saves recent turns, records practice stats, and awards **courage badges**.

### The modes

All four speaking modes run over the single WebSocket `/ws/interview`; `mode` is set in the `start` message. Modes live in `interview/engine.py` (`MODES = ("interview", "conversation", "learning", "daily")`) and `test_client.html`.

| Mode (code name) | UI name | Language | What it does | Ends? / Report |
|---|---|---|---|---|
| `conversation` | **Talk** / Confidence Talk / Start Speaking | English | Free, warm English chat that never ends; follows the user's interests, gently offers new topics if they go quiet. `conversation_system` prompt. | Soft cap at `conversation_max_turns` = 40 (`capped` → gentle wrap-up) |
| `interview` | **Interview** / Interview Prep | English | Adaptive mock HR interview; covers competencies (`self_introduction, role_motivation, project_depth, communication, strengths_weakness`), self-ends with `INTERVIEW_COMPLETE:` marker (~6–8 turns), hard cap `interview_max_turns` = 15. `interviewer_system` prompt. | **Scored report** via `SCORER_SYSTEM`: overall + grammar/fluency/confidence/communication/vocabulary/professionalism, filler words, strengths, fixes, and a rewritten "better_answer" |
| `learning` | **Learn** | Hindi/Hinglish → English | User says a Hindi/Hinglish sentence; DuSu returns the natural spoken-English translation (`TRANSLATE_SYSTEM`). Practice translating on demand, no persona. | No report; not persisted to memory |
| `daily` | **Daily Talk** | Hindi-first (Latin-script Hinglish reply) | Hindi-first "close friend" day chat. One JSON call (`DAILY_TURN_SYSTEM`) returns: `english` (clean translation of what they said), `reply_hindi` (warm friend reply), `next_question_hindi`, a tiny `tip`, sensed `mood`, and `context` (plans/weather/events). Resumes from `dusu_daily_resume` localStorage. | No report; records practice (+20 xp), saves daily context |

### The dynamic level test (onboarding assessment)

First-time users (server `onboarded == false`) are routed into a **dynamic, model-generated level check** — not a fixed quiz:

1. `POST /leveltest/gen` — the LLM freshly generates the test items each time (`repeat` sentence, `think_hindi` prompt, `open` question). This doubles as a **key verification** step (it fails if the user's keys don't work).
2. Four spoken tasks are transcribed in-browser: **Task 1** self-intro, **Task 2** repeat-after-me (listening/pronunciation), **Task 3** Hindi→English (thinking), **Task 4** open question (confidence/vocab), plus 3 MCQs (goal / comfort / practice_time).
3. `POST /assessment` scores 6 skills 0–100 (confidence, pronunciation, listening, vocabulary, grammar, thinking) and assigns a **CEFR level A0–B2** (`ASSESS_SYSTEM`). Result seeds the profile + the 7-level roadmap. Message can be returned in Hindi (`lang="hi"`, Latin script).

Deterministic post-login gate (`routeAfterLogin`): **keys → test → home**.

There is also a **7-level curriculum** ("worlds") with per-level lessons and a boss/Level Test that gates level-up (`POST /level/test/submit`, pass ≥ 70 via `LEVEL_TEST_SYSTEM`; individual lessons via `/lesson/evaluate` + `/lesson/complete`). Worlds (`_WORLD_NAMES` / client `WORLD_NAMES`): **The Village → The Street → The City → The Workplace → The Interview Hall → The Boardroom → The Global Stage**. Levels: Thinking in English, Simple Speaking, Daily Conversation, Confidence, Interview, Professional English, Fluency (`CURRICULUM` in the client; `LEVEL_LESSON_COUNTS`/`MAX_LEVEL=7`/`XP_PER_LESSON=20` on the server). Gamification: xp, coins, streak_days, daily_goal, and badges (`BADGE_LABELS`: first_lesson, first_converse, streak_7, sentences_100, level_up, and courage_* badges).

### BYOK / Office vs Personal, and roles

DuSu runs on shared free LLM quota, so there is a **Bring-Your-Own-Keys** system to stop the shared quota from being drained:

- **Personal mode** — uses OUR default key chain (from `.env`).
- **Office / BYOK mode** — the user supplies their own free API keys (Gemini / Groq / OpenRouter / GitHub), stored in browser localStorage (`dusu_office_keys`) and routed per-request via `set_active_keys()` (contextvar-isolated per connection). **Minimum 2 verified keys** to start (`hasOwnKeys()` → `keyCount() >= 2 && keysVerified()`). Keys are tested with a tiny live call at `POST /keys/verify`.
- **Global switch** — owner-controlled `require_own_keys` setting (default ON). When ON, any non-free user MUST BYOK before the test or any talk (`resolve_keys()` → HTTP 402 `keys_required`).

**Roles** (`role_for()` in `main.py`):

| Role | Who | Access |
|---|---|---|
| `owner` | `david123rana@gmail.com` (hard-coded `OWNER_EMAILS`) | Full admin + unlimited default-key use |
| `unlimited` | `shuhanisuhana037@gmail.com` (`UNLIMITED_EMAILS`) | Unlimited default-key use |
| `user` (default) | Everyone else | Must BYOK when `require_own_keys` is ON |
| **free-access** | Any email the owner adds to the "Office/free" allowlist (`office_add`, e.g. "Surendri") | May use OUR default keys even in require-own-keys mode |

Owner-only admin endpoints: `/admin/overview`, `/admin/settings` (flip the switch), `/admin/action` (approve/block/unblock/delete), `/admin/office` (add/remove free-access email), `/admin/wipe` (reset all test users except owner/unlimited/free-access). Normal users choosing Office go to `pending` (needs owner approval). User `status`: active / pending / blocked.

### Monetization notes

The plans frame DuSu as a **premium confidence product** ("Calm × Duolingo × a luxury concierge"), selling the *outcome* (a job / interview readiness), not grammar. Principle: **start free, feel premium**; zero-friction entry. Current stack is intentionally **$0**; the roadmap (`AI-Interview-Coach-Plan.md`, `DUSU.md`) lists future paths: paid model swap for quality, saved history, company-specific interview packs, streaks/progress, video mode, and **institute/college dashboards (B2B2C)**. No payment code exists yet; the BYOK/Office split is the current cost-control mechanism. Killer metric per the plan: **turn latency < 800 ms** (hard ceiling 1.2 s).

### Tech stack (as shipped)

| Layer | Choice | Where |
|---|---|---|
| Frontend | Single HTML file, vanilla JS/CSS, PWA + Android TWA | `backend/test_client.html`, `manifest.webmanifest`, `sw.js`, `android-twa/` |
| Backend | FastAPI + one WebSocket `/ws/interview` | `backend/app/main.py` (~1,045 lines) |
| Speech | Browser **Web Speech API** (STT) + **speechSynthesis** (TTS) — Chrome/Edge | in `test_client.html` |
| LLM | Multi-provider OpenAI-compatible fallback chain: **gemini → groq → openrouter → github**, with per-provider cooldowns | `config.py`, `providers/openrouter_provider.py` (`_complete`) |
| Auth | Google Sign-In → HMAC-signed 30-day stateless session token | `auth.py` |
| DB | Self-hosted Postgres (`db` service in `docker-compose.yml`) via SQLAlchemy 2.0 async + asyncpg; **graceful degrade** if `DATABASE_URL` empty (`db_enabled`) | `db.py` |
| Hosting | Docker Compose on the host box (backend + Postgres), fronted by cloudflared at `dusu.ranabrothers.online` (legacy `dusu.ruralrootcloud.com` still served) | `docker-compose.yml`, `cloudflare/TUNNEL.md` |

**DB tables** (`db.py`): `users` (id=Google sub, email, name, picture, status, mode), `profiles` (onboarded, goal, comfort, practice_time, CEFR level, scores JSONB, weak_areas), `progress` (xp, coins, streak_days, sessions_today, daily_goal, badges, journey JSONB), `memory` (single JSONB `facts` doc — the emotional layer), `conversations` (one summary row per finished session), plus a key/value `settings` table.

**Key env vars** (`config.py` / `.env.example`): `OPENROUTER_API_KEY`, `GEMINI_API_KEY`, `GROQ_API_KEY`, `GITHUB_TOKEN`, `GOOGLE_CLIENT_ID`, `SESSION_SECRET`, `DATABASE_URL`, `ANDROID_TWA_PACKAGE` (default `com.dusu.app`), `ANDROID_CERT_SHA256`, `HOST`, `PORT`, plus limits `MAX_SESSIONS_PER_DAY` (20), `CONVERSATION_MAX_TURNS` (40), `INTERVIEW_MAX_TURNS` (15).

**WebSocket protocol** — client→server: `start` (mode, token, keys, name, role, mood, hour, seed, resume), `user_text`, `end`, `close`. Server→client: `status`, `ai_text`, `daily_question`, `daily_turn`, `translation`, `ready`, `interview_done`, `report`, `limit`, `quota`, `keys_required`, `auth_error`, `error`, `ended`.

**localStorage keys** (client): `dusu_token`, `dusu_user`, `dusu_state`, `dusu_onboarded`, `dusu_usemode` (personal|office), `dusu_office_keys`, `dusu_keys_ok`, `dusu_voice`, `dusu_daily_resume`, `dusu_letter`, `dusu_think`, `dusu_usage`.

### The `.md` files at repo root (what each is)

> These are planning/spec docs. Several predate the shipped code — the sections above reflect the **code as it actually is now**; the docs are noted where they diverge.

| File | What it is | Current vs code |
|---|---|---|
| `DUSU.md` | Living product overview — vision, modes, brand, $0 stack | Mostly accurate, but lists only 2 live modes; code now has **4** (adds Learn + Daily Talk) |
| `DUSU-JOURNEY.md` | Plan for turning DuSu into a coach with DB + assessment + 7-level journey + gamification | Largely **shipped** (Neon, assessment, journey, badges) |
| `DUSU_FEATURES.md` | Complete feature map: 11 screens, every feature → screen → frontend/backend/data. Best single "where things live" doc | Closely matches code (dated 2026-07-21) |
| `DUSU_EXPERIENCE.md` | "S11 — The Living Conversation" flagship spec for the Start-Speaking / Companion Moment; defines premium Hinglish (~55/45) | Reflects the shipped `/greeting` + Companion Moment |
| `DUSU_COMPANION_SYSTEM.md` | The emotional retention/relationship system — Emotion Ladder, relationship stages, moments, the "One Law" | Core ideas (stages, moments, memory) are **implemented** in `db.py`/`main.py` |
| `DUSU_HOME_UI.md` | Mobile-first Home UI label map — one worded button ("Start Speaking"), "More ▾" reveal, icons | Matches the shipped home |
| `BRAND-UI-PLAN.md` | Brand + premium UI system: positioning, palette (navy + gold), type (Cormorant Garamond + Inter), logo rules | Design source of truth |
| `DUSU_BYOK_PLAN.md` | Office vs Personal BYOK plan (marked "PLAN ONLY") | Now **shipped** — BYOK, `/keys/verify`, `require_own_keys`, 2-key minimum all exist |
| `DUSU_ICON_BRIEF.md` | App-icon/logo brief — the "D-mark" (face + speech-bubble + sound-waves), gold-on-navy | Design brief |
| `DUSU_LOCAL_CLOUDFLARE_PLAN.md` | Plan to run local-first via Cloudflare with Render/Neon fallback; domain `dusu.ranabrothers.online` | **Not built** except PWA/TWA items; Render+Neon is current |
| `AI-Interview-Coach-Plan.md` | Original A→Z go-to-market + roadmap (the "confidence-for-interviews" thesis, latency metric) | Foundational/historical |
| `VOICE-AVATAR-PLAN.md` | Plan to move TTS server-side (neural voice + lip-synced anime avatar) | **Not built** — TTS is still browser `speechSynthesis` |
| `DEPLOY.md` | Free-deploy guide — why Render (WebSockets, always-on, HTTPS), $0 host comparison | Deployment reference |
| `backend/README.md` | Backend v0 run/setup docs (interview MVP era) | Setup accurate; describes pre-DB single-interview state |

Note: the `backend/README.md` and some plans still describe the earlier "interview-only, OpenRouter-only, no-DB" MVP; the code has since grown to 4 modes, a 4-provider chain, Neon persistence, the companion/memory system, BYOK, roles/admin, the 7-level journey, and PWA/TWA packaging.

---

## 2. Architecture & Repo Layout

DuSu is a **$0-stack, browser-first spoken-English coach**. All speech (STT + TTS) happens in the user's browser via the Web Speech API; the server is text-only and stateless-capable. One FastAPI process serves both the single-file HTML frontend and the WebSocket/HTTP API, backed by a free LLM fallback chain and its own Postgres container.

### Component diagram

```
┌──────────────────────────────────────────────────────────────────────────┐
│  BROWSER (Chrome/Edge only — Web Speech API)                               │
│                                                                            │
│   mic ─► SpeechRecognition (STT)  ─┐          ┌─► SpeechSynthesis (TTS) ─► speaker
│                                    │  text     │   (window.speechSynthesis)│
│   backend/test_client.html  ◄──────┴───────────┘                           │
│   (ONE 4135-line file: HTML+CSS+JS; all screens, all state)                │
│   • Google Identity Services (GIS) sign-in widget                          │
│   • localStorage: dusu_token, dusu_user, dusu_state, dusu_onboarded, …     │
└───────────────┬───────────────────────────────┬───────────────────────────┘
      WSS text-only │  /ws/interview     HTTPS JSON │ /auth,/me,/assessment,/lesson,…
                    ▼                               ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  FastAPI  (backend/app/main.py)  — uvicorn, served on Render / local PC    │
│  • WebSocket /ws/interview → interview/engine.py (Session per socket)      │
│  • HTTP endpoints (auth, home, roadmap, admin, BYOK keys)                  │
│  • auth.py  (Google ID-token verify + HMAC session tokens, no DB needed)   │
│  • config.py Settings → LLM provider chain                                 │
└───────────────┬───────────────────────────────┬───────────────────────────┘
                ▼                                 ▼
┌───────────────────────────────┐   ┌────────────────────────────────────────┐
│ FREE LLM CHAIN (OpenAI-compat) │   │ Postgres — the `db` compose service     │
│ providers/openrouter_provider  │   │ asyncpg)  — backend/app/db.py           │
│ tried in order, auto-failover: │   │ Tables: users, profiles, progress,      │
│  1 gemini  2 groq              │   │ memory(JSONB), conversations,            │
│  3 openrouter  4 github        │   │ office_emails, settings                  │
│ (per-provider cooldown on 429) │   │ EMPTY DATABASE_URL ⇒ app still runs      │
│ BYOK: per-request key override │   │ fully, just stateless (db_enabled=False) │
└───────────────────────────────┘   └────────────────────────────────────────┘
```

Optional edge layer: a **Cloudflare Worker** (`cloudflare/worker.js`) fronts one stable hostname (`dusu.ranabrothers.online`) and routes to the local PC (via cloudflared tunnel) when healthy, else to Render — both share the same Neon DB so failover never splits data.

### The text-only WebSocket protocol (`/ws/interview`)

The browser does all audio. Only **text JSON frames** cross the wire — the LLM is the brain, never the ears/voice. One `Session` object (`interview/engine.py`) lives per socket and holds the full transcript in memory. Four modes multiplex over the same socket: `interview`, `conversation`, `learning`, `daily`.

**Client → server**

| Frame | Fields | Notes |
|---|---|---|
| `start` | `mode`, `name`, `role`, `token`, `mood`, `seed`, `keys`, `hour`, `resume` (+ `reconnect`, `resume`, `elapsed` on a quiet reconnect, section 21) | Opens a session. `keys` = BYOK dict `{gemini,groq,openrouter,github}`. `seed` = user's spoken reply to the Companion greeting (conversation). `resume` = last localStorage turns (daily). `hour` (0–23) → time-of-day. |
| `user_text` | `text` | One finished spoken turn (already transcribed by browser STT). |
| `end` | — | Finish: interview → report; others → `ended`. Also fires `_persist_session()`. |
| `ping` | — | Is this socket alive? Answered with `pong` (the page asks after a long screen lock). |
| `close` | — | Break the loop. |

**Server → client**

| Frame | Fields | Meaning |
|---|---|---|
| `status` | `msg` | e.g. `"starting"`, `"thinking"`, `"scoring"`, `"translating"`. |
| `ai_text` | `text` | DuSu's spoken line (interview/conversation); browser TTS speaks it. |
| `ready` | — | Learning mode ready (client greets in Hindi). |
| `pong` | — | The answer to `ping`. |
| `daily_resumed` / `session_resumed` | `lang` / `mode`, `lang` | The server took a quiet reconnect (Daily Talk / every other chat): same chat, no greeting, no model call (section 21). |
| `translation` | `hindi`, `text` | Learning mode: Hindi input → English. |
| `translate_error` | — | Learning/daily failure (non-quota). |
| `daily_question` | `question` | Daily mode opener (Hindi/Hinglish). |
| `daily_turn` | `hindi`, `english`, `reply`, `tip`, `next_question` | Daily mode reply bundle. |
| `interview_done` | — | Interviewer wrapped up (`INTERVIEW_COMPLETE:` marker or turn cap). |
| `report` | `data` | Scored interview JSON (rubric in `SCORER_SYSTEM`). |
| `ended` | — | Non-interview session ended. |
| `limit` | `msg` | Conversation hit `conversation_max_turns` (40). |
| `quota` | `msg` | All keys hit their rate limit (429/402/etc.). |
| `keys_required` | `msg` | BYOK required but none supplied → must add keys in Settings. |
| `auth_error` | `msg` | Session invalid → client logs out. |
| `error` | `msg` | Generic failure. |

WS URL is derived client-side: `(https→wss)://<host>/ws/interview`. HTTP endpoints exist for everything non-conversational (auth, onboarding assessment, roadmap lessons/tests, home cards, admin, BYOK key verification) — see the `@app.get/post` handlers in `main.py`.

### Repo directory tree

Root is a git repo (`main` branch). Build artifacts, `.venv`, and `.env` are git-ignored (`DuSu.apk`, `**/.env`, `**/.venv/`, `__pycache__`, `backend/users.db`).

```
c:\Personal Work\English Specking\
├── backend/                         THE APP — FastAPI server + PWA frontend + assets
│   ├── app/
│   │   ├── main.py                  FastAPI app: all HTTP endpoints + /ws/interview WS; role/access
│   │   │                            gating (OWNER_EMAILS, UNLIMITED_EMAILS), BYOK key routing,
│   │   │                            assetlinks.json, config injection into index HTML
│   │   ├── config.py                pydantic Settings from .env; providers()/providers_from() build the
│   │   │                            4-provider LLM chain (gemini→groq→openrouter→github); usage caps
│   │   ├── auth.py                  Google ID-token verify + HMAC-signed stateless session tokens (30-day)
│   │   ├── db.py                    Postgres, self-hosted (SQLAlchemy 2.0 async). Tables: users, profiles,
│   │   │                            progress, memory(JSONB), conversations, office_emails, settings.
│   │   │                            Roadmap logic (7 levels), XP/streak/badges, emotional memory,
│   │   │                            leaderboard, relationship stages, admin ops. No-op if no DATABASE_URL
│   │   ├── interview/
│   │   │   ├── engine.py            Session class: per-socket transcript + turn logic for all 4 modes;
│   │   │   │                        interview self-end (INTERVIEW_COMPLETE:), turn caps, daily_turn(),
│   │   │   │                        summarize_and_extract() (end-of-session memory)
│   │   │   └── prompts.py           All system prompts + personas: DUSU_PERSONA, interviewer/conversation,
│   │   │                            SCORER, ASSESS, DAILY_TURN, GREETING, LETTER, TRANSLATE, LEVEL_TEST,
│   │   │                            LESSON_EVAL, SESSION_MEMORY; COMPETENCIES list
│   │   ├── providers/
│   │   │   ├── base.py              LLMProvider Protocol (next_question / score) — vendor-agnostic
│   │   │   ├── openrouter_provider.py  OpenAI-client impl driving ALL providers; _complete() walks the
│   │   │   │                        chain+models with cooldown; set_active_keys() (BYOK via contextvar);
│   │   │   │                        _extract_json() for messy LLM JSON
│   │   │   └── __init__.py          Wiring: `llm = OpenRouterLLM()`
│   │   └── __init__.py
│   ├── test_client.html             ENTIRE FRONTEND — one 4135-line file (HTML+CSS+JS). All screens:
│   │                                onboarding, level test, home/companion, conversation, daily talk,
│   │                                learning, 7-level roadmap CURRICULUM, leaderboard, settings, admin.
│   │                                Web Speech STT/TTS, GIS login. Placeholders __GOOGLE_CLIENT_ID__,
│   │                                __AUTH_ENABLED__, __MAX_SESSIONS__ injected at GET /
│   ├── manifest.webmanifest         PWA manifest (name DuSu, standalone, #070a14, /logo.png icons)
│   ├── sw.js                        Service worker (cache "dusu-v5"); network-first navigations,
│   │                                never caches /ws,/auth,/me,/lesson,/level,/assessment,/admin,/keys,…
│   ├── logo.png                     App icon / PWA icon (served at /logo.png)
│   ├── assets/assistant/            8 anime character PNG frames (idle, blink, happy, listening,
│   │                                thinking, talk_01-03) served at /assets/… (mostly unused now)
│   ├── requirements.txt             fastapi 0.115.6, uvicorn, openai 1.59.6, pydantic 2, sqlalchemy 2,
│   │                                asyncpg, google-auth, greenlet
│   ├── runtime.txt                  python-3.12.7 (Render)
│   ├── Procfile                     `web: uvicorn app.main:app --host 0.0.0.0 --port $PORT`
│   ├── .env                         REAL secrets (git-ignored): GEMINI/GROQ/OPENROUTER/GITHUB keys,
│   │                                GOOGLE_CLIENT_ID, SESSION_SECRET, HOST, PORT (DATABASE_URL comes from compose)
│   ├── .env.example                 Template (note: mentions older single-OpenRouter setup — code truth
│   │                                is config.py's 4-provider chain)
│   └── README.md                    Backend run instructions + call-flow diagram (v0-era)
│
├── android-launcher/                Android app #1 (pkg com.dusu.launcher): thin launcher that opens
│   │                                DuSu in the phone's REAL Chrome (external browser, so Web Speech works)
│   ├── app/src/main/AndroidManifest.xml, MainActivity.kt, Notifications.kt, BootReceiver.kt,
│   │   ReminderReceiver.kt          Offline gate + daily reminder notification + boot re-arm
│   ├── app/src/main/res/…           strings.xml (dusu_url = https://dusu-app-1.onrender.com), icons, layout
│   ├── build.gradle.kts, settings.gradle.kts, gradlew(.bat), gradle/…  Gradle build
│   └── README.md                    (build/ .gradle/ .idea/ present locally = git-ignored build output)
│
├── android-twa/                     Android app #2 (pkg com.dusu.app): Trusted Web Activity — runs DuSu
│   │                                full-screen INSIDE the app on Chrome's engine (Web Speech works, no
│   │                                address bar once assetlinks verified). Installs side-by-side with launcher
│   ├── app/src/main/AndroidManifest.xml   TWA + LauncherActivity, asset_statements, 4-hourly reminder
│   ├── app/src/main/java/com/dusu/app/MainActivity.kt  Offline check → TwaLauncher; crash-to-file screen
│   │   Notifications.kt, BootReceiver.kt, ReminderReceiver.kt
│   ├── app/src/main/res/…           strings.xml (launchUrl + hostName = dusu-app-1.onrender.com,
│   │                                asset_statements JSON), adaptive icons
│   ├── gen_icons.py, icon-master.png, play-icon-512.png   Icon generation source
│   ├── build.gradle.kts, settings.gradle.kts, gradlew…
│   └── README.md                    TWA build + assetlinks setup (needs ANDROID_CERT_SHA256 env on server)
│
├── cloudflare/                      Local-first edge failover
│   ├── worker.js                    Worker: route to PC_ORIGIN (pc.ranabrothers.online tunnel) if /health
│   │                                OK, else CLOUD_ORIGIN (Render); WS pass-through; 10s health cache
│   ├── wrangler.toml                Worker config: route dusu.ranabrothers.online/*, PC/CLOUD origin vars
│   └── README.md                    cloudflared tunnel + wrangler deploy steps
│
├── .github/workflows/build-apk.yml  CI: builds android-LAUNCHER debug APK (JDK17, SDK 34) on push,
│                                     uploads artifact (does NOT build the TWA module)
├── image/                           Two ChatGPT-generated brand mockup PNGs
│
├── DuSu-app.apk                     Built TWA APK (~3 MB, com.dusu.app) — committed
├── DuSu.apk                         Older launcher APK (~6 MB) — GIT-IGNORED (in .gitignore)
├── Logo.png                         Master brand logo (~1.3 MB, root copy)
│
├── *.md  (planning/spec docs — SOME ARE OLD PLANS; verify against code):
│   ├── AI-Interview-Coach-Plan.md   Original A→Z build plan (interview-app origin)
│   ├── DUSU.md                      Product one-pager ("Speak with confidence")
│   ├── DUSU-JOURNEY.md              Plan: translator/interview bot → personal AI coach with a journey
│   ├── DUSU_FEATURES.md             Complete feature map (feature → screen → frontend/backend/data)
│   ├── DUSU_COMPANION_SYSTEM.md     The 4-type memory + relationship-stage "companion" design (S1–S6)
│   ├── DUSU_EXPERIENCE.md           S11 "Living Conversation" final experience spec
│   ├── DUSU_HOME_UI.md              Mobile-first home UI map (one big "Start Speaking" button)
│   ├── DUSU_BYOK_PLAN.md            Bring-Your-Own-Token (Office vs Personal) plan — now implemented
│   ├── DUSU_LOCAL_CLOUDFLARE_PLAN.md  Local-first + Render fallback plan (matches cloudflare/)
│   ├── DUSU_ICON_BRIEF.md           Logo / app-icon design brief
│   ├── BRAND-UI-PLAN.md             Branding + premium UI design language
│   ├── VOICE-AVATAR-PLAN.md         Voice + animated-avatar upgrade plan
│   └── DEPLOY.md                    Free ($0) deployment plan (Render + PWA)
│
├── .gitignore                       Ignores .env, .venv, __pycache__, users.db, DuSu.apk
└── .claude/settings.local.json      Local Claude Code settings
```

### Key runtime facts (verified in code)

- **LLM provider chain order** (`config.py`): `gemini` → `groq` → `openrouter` → `github`, each with its own model fallback list; a provider hit with 429/quota is cooled down (90s, or 1800s for daily-quota errors). `.env` var names: `GEMINI_API_KEY`, `GROQ_API_KEY`, `OPENROUTER_API_KEY`, `GITHUB_TOKEN`.
- **Other env vars**: `GOOGLE_CLIENT_ID` (enables login), `SESSION_SECRET` (HMAC token signing — falls back to random per-process if left as `dev-change-me`), `DATABASE_URL` (injected by compose from the `db` service; empty ⇒ stateless), `HOST`, `PORT`; plus `ANDROID_TWA_PACKAGE` and `ANDROID_CERT_SHA256` (read by `main.py` for `/.well-known/assetlinks.json`). Usage caps `max_sessions_per_day=20`, `conversation_max_turns=40`, `interview_max_turns=15`.
- **Access model** (`main.py`): `OWNER_EMAILS = {david123rana@gmail.com}`, `UNLIMITED_EMAILS = {shuhanisuhana037@gmail.com}`; a DB-backed `office_emails` allowlist grants "free access" to the default keys; a global `require_own_keys` setting (owner-toggled) forces everyone else into BYOK.
- **Frontend localStorage keys**: `dusu_token`, `dusu_user`, `dusu_state`, `dusu_onboarded`, `dusu_usemode`, `dusu_office_keys`, `dusu_keys_ok`, `dusu_voice`, `dusu_daily_resume`, `dusu_letter`, `dusu_usage`, `dusu_think`.
- **Live origins**: Render app `https://dusu-app-1.onrender.com`; stable Cloudflare front door `https://dusu.ranabrothers.online`; PC tunnel `https://pc.ranabrothers.online`.

---

## 3. Backend API (`backend/app/main.py`)

The single FastAPI application. Text-only wire protocol — the browser does STT/TTS via the Web Speech API, so the server only ever exchanges text; Claude/LLM is the "brain". File header docstring (lines 1–17) documents the core WS shapes. App object: `app = FastAPI(title="DuSu")` (line 37).

Key imports/wiring:
- `from .config import settings` — provider chains, limits, Google client id, secrets (see `backend/app/config.py`).
- `from .interview.engine import Session` — the per-connection conversation state machine used by `/ws/interview`.
- `from .interview.prompts import ASSESS_SYSTEM, LESSON_EVAL_SYSTEM, LEVEL_TEST_SYSTEM, LETTER_SYSTEM, GREETING_SYSTEM` — system prompts.
- `from .providers import llm` — `llm.assess()`, `llm.next_question()`, `llm.generate()`.
- `from .providers.openrouter_provider import set_active_keys` — sets the effective key chain for the current request/connection (BYOK routing).
- `from . import auth` and `from . import db`.

Startup hook `@app.on_event("startup") _startup()` (lines 86–88) calls `await db.init_db()` (no-op when no `DATABASE_URL`).

### Roles & access gating (module-level, lines 39–83)

| Name | Kind | Definition / behavior |
|---|---|---|
| `OWNER_EMAILS` | `set` | `{"david123rana@gmail.com"}` — full admin + unlimited. |
| `UNLIMITED_EMAILS` | `set` | `{"shuhanisuhana037@gmail.com"}` — unlimited, no admin. |
| `role_for(email) -> str` | fn | Lowercases/strips; returns `"owner"`, `"unlimited"`, or `"user"`. |
| `free_access(email) -> bool` | async fn | May use OUR default keys? True for owner/unlimited, or if `db.office_has(email)` (owner-added free/Office email). Aliased as `office_allowed = free_access`. |
| `require_own_keys_on() -> bool` | async fn | Global owner switch; reads `db.get_setting("require_own_keys", "1")`; `"1"` → ON. Defaults True on any error. |
| `resolve_keys(email, keys) -> (ok, effective_keys_or_None, reason)` | async fn | The BYOK gate. If switch OFF **or** user is free → `(True, None, "")` (use default chain). Else if `keys` has any non-empty value → `(True, keys, "")` (use their keys only). Else `(False, None, "keys_required")`. |
| `_is_quota(e) -> bool` | fn | True if error string contains any of `429`, `quota`, `exhaust`, `rate limit`, `unavailable`, `insufficient`, `402`. Used to distinguish "keys hit limit" from real errors. |

`_bearer(header, token)` (lines 198–202): prefers `Authorization: Bearer <t>` header, else falls back to a `token` query/body value.

`_require_owner(token, authorization)` (lines 289–295): reads session, 401 if not signed in, 403 `"Owner only"` if `role_for != "owner"`.

`_send(ws, **payload)` (lines 746–747): `ws.send_text(json.dumps(payload))`.

### Authentication (`backend/app/auth.py`)

Google Sign-In + **stateless HMAC** session tokens; no server-side session store.
- `auth_enabled = bool(settings.google_client_id)`.
- `_SECRET = settings.session_secret`; if it's still the default `"dev-change-me"`, a random per-process secret is generated (warns to set `SESSION_SECRET` for stable sessions).
- `verify_google(credential)` — `google.oauth2.id_token.verify_oauth2_token` against `GOOGLE_CLIENT_ID`, `clock_skew_in_seconds=60`; returns `{sub, email, name, picture}`.
- `make_session(user, ttl=30*86400)` — 30-day token, payload `{sub, email, name, exp}`, encoded `base64url(payload).base64url(HMAC-SHA256(secret, body))`, joined by `.`.
- `read_session(token)` — splits on `.`, verifies HMAC with `hmac.compare_digest`, checks `exp`; returns claims dict or `None`.

### Static / well-known routes

| Method | Path | Serves | Notes |
|---|---|---|---|
| GET | `/` | `backend/test_client.html` (`_CLIENT_HTML`) | Reads file, replaces placeholders `__GOOGLE_CLIENT_ID__` → `settings.google_client_id`, `__AUTH_ENABLED__` → `"true"/"false"`, `__MAX_SESSIONS__` → `settings.max_sessions_per_day`. Fallback stub HTML if file missing. |
| — (mount) | `/assets/*` | `backend/assets/` (`_ASSETS`, `StaticFiles`) | Directory created at import; holds the anime character PNG frames. |
| GET | `/logo.png` | `backend/logo.png` (`_LOGO`) | `FileResponse`. |
| GET | `/manifest.webmanifest` | `backend/manifest.webmanifest` (`_MANIFEST`) | media type `application/manifest+json`. |
| GET | `/sw.js` | `backend/sw.js` (`_SW`) | media type `application/javascript`; headers `Cache-Control: no-cache`, `Service-Worker-Allowed: /` (root scope). |
| GET | `/.well-known/assetlinks.json` | JSON | Digital Asset Links for the Android TWA. Reads env `ANDROID_CERT_SHA256` (comma/newline-separated SHA-256 fingerprints, upper-cased) and `ANDROID_TWA_PACKAGE` (`_TWA_PACKAGE`, default `"com.dusu.app"`). Returns one statement: `relation ["delegate_permission/common.handle_all_urls"]`, `target {namespace:"android_app", package_name, sha256_cert_fingerprints}`. Header `Cache-Control: public, max-age=3600`. |
| GET | `/health` | `{ok, has_key, providers}` | `providers = settings.providers()`; `has_key=bool(providers)`; `providers` = list of active provider names. |

Path constants (lines 90–97): `_BACKEND = <repo>/backend`, and the four static files + `_ASSETS` all live directly under `backend/`.

### HTTP endpoints

All request bodies are Pydantic models. Most write endpoints carry `token` in the body; read endpoints (`/me`, `/leaderboard`, admin GET) accept `token` query **or** `Authorization: Bearer` header via `_bearer`.

#### `POST /auth/google` — `GoogleIn{credential:str}`
Verifies Google ID token. 500 if `auth_enabled` false; 401 on verify failure. Returns `{token: <session>, user: <claims>}`. If DB enabled, calls `db.login(claims)` and adds `onboarded`, `profile`, `progress`.

#### `GET /me` — query `token` / Bearer
Signed-in user's full state for reload/routing. 401 if no session. Always injects `role` (`role_for`), `email`, `office_allowed` & `free_access` (both = `free_access(email)`), `require_own_keys` (`require_own_keys_on()`). If no DB → returns those flags with `onboarded: None`. With DB → `db.login(claims)` state; if `onboarded`, also builds `today` (`db.build_today`), `growth` (`db.build_growth`), `opening` (`db.build_opening`), `recommendations` (`db.build_recommendations`). On DB error returns `{onboarded: False}`.

#### `GET /leaderboard` — query `token` / Bearer
Top learners by all-time XP (private aliases) + caller's rank. 401 if no session. No DB → `{top:[], you:null}`. Else `db.leaderboard(claims["sub"])`.

#### `POST /keys/verify` — `KeysIn{token:str="", keys:dict={}}` (+ Bearer)
BYOK key tester. 401 if no session. For each `settings.providers_from(keys)` entry, makes a tiny `AsyncOpenAI` chat call ("Reply OK", `max_tokens=8`). Returns `{results: {<provider>: {ok:bool, error:str}}}`. Special error text for GitHub token missing `models` permission; distinguishes invalid key vs quota-exhausted (`ok=True` with a "quota exhausted" note).

#### `POST /assessment` — `AssessIn`
Scores the onboarding level assessment. Fields: `token`, `keys={}`, `lang="en"` (`"hi"`/`"en"`), `about: AboutIn|None`, `goal`, `comfort`, `practice_time`, `intro` (task 1), `repeat_target`/`repeat_said` (task 2), `think_hindi`/`think_said` (task 3), `open_said` (task 4). `AboutIn{nickname, native_lang, profession, dream, interests:dict}`.
Flow: 401 if no session → `resolve_keys` gate (402 `"keys_required"` if fails) → `set_active_keys(eff)` → build text payload (Hindi note appended if `lang=="hi"`) → `llm.assess(ASSESS_SYSTEM, payload)` (502 on failure). Persists via `db.login` + `db.save_assessment` (returns seeded `progress`) + `db.save_about` (adds `native_lang`, `intro_text`). Returns `{profile:{goal,comfort,practice_time,level,scores,weak_areas}, message, progress}`.

#### `POST /leveltest/gen` — `GenIn{token:str="", keys:dict={}}`
Dynamic level-check generator (also verifies the user's keys work). 401 if no session → `resolve_keys` (402 `"keys_required"`) → `set_active_keys(eff)`. Inline system prompt asks for fresh JSON `{repeat, think_hindi, open}` for a Hindi-L1 learner. `llm.assess(sys, "Generate a fresh level check now.")`. On quota → 429 `"quota"`; other errors → 502 `"gen_failed"`. Returns `{repeat, think_hindi, open}`.

#### `POST /checkin` — `CheckinIn{token, mood}`
401 if no session. No DB → `{ok:True}`. Else `db.save_checkin(sub, mood)` → `{ok:True, memory: facts}` (or `{ok:False}`).

#### `POST /greeting` — `TokenIn{token, keys={}}`
The "Companion Moment" Hinglish greeting from memory. `set_active_keys(inp.keys)` then 401 check. No DB → `{text:""}`. Builds payload from `db.build_companion_context` + `db.recent_summaries(uid,1)` (name, stage, days_together, identity, moments, achievements, energy_today, next_hook, world, last_session) → `llm.next_question(GREETING_SYSTEM, [...])`. Returns `{text}`.

#### `POST /futureme` — `FutureMeIn{token, text}`
401 if no session. No DB or empty text → `{ok:True}`. Else `db.save_future_me(sub, text)` → `{ok:True, memory: facts}` / `{ok:False}`.

#### `POST /letter` — `TokenIn{token, keys={}}`
This week's personal note from DuSu. `set_active_keys(inp.keys)` then 401. No DB → `{letter:None}`. Regenerates at most once per 7 days and only if `progress.xp >= 20`; otherwise returns cached `last_letter` with `fresh:False`. Builds prompt from memory/progress/`db.recent_summaries(sub,5)` → `llm.generate(LETTER_SYSTEM, prompt, max_tokens=350)` → `db.save_letter` → `{letter:{date,text}, fresh:True}`.

#### `POST /lesson/evaluate` — `LessonEvalIn{token, keys={}, lang="en", type="speak", prompt, target, said}`
Scores one spoken lesson answer, no DB write. `set_active_keys(keys)` then 401. `llm.assess(LESSON_EVAL_SYSTEM, payload)` (502 on failure). Returns the LLM's JSON directly.

#### `POST /lesson/complete` — `LessonDoneIn{token, level:int, lesson_id, lesson_type=""}`
401 if no session. No DB → `{progress:None, leveled_up:False, new_badges:[]}`. Else `db.login` + `db.complete_lesson(sub, level, lesson_id, lesson_type)` (updates journey/xp/streak/badges); 500 on failure.

#### `POST /level/test/submit` — `LevelTestIn{token, keys={}, level:int, lang="en", items:[LevelTestItem]}`
`LevelTestItem{prompt="", target="", said=""}`. Scores a whole Level Test in one call. `set_active_keys(keys)` then 401. `llm.assess(LEVEL_TEST_SYSTEM, payload)` (502 on failure). Robust score parsing (handles null/`"70%"`/`"eighty"`), clamps 0–100. Returns `{score, passed(score>=70), items, message}`; with DB adds `leveled_up`, `new_badges`, `progress` via `db.submit_level_test`.

#### `POST /mode` — `ModeIn{token, mode}` (`personal` | `office`)
401 if no session. Normal `user` choosing `office` → `status="pending"` (needs owner approval); owner/unlimited or `personal` → `"active"`. Persists `db.set_user_mode(sub, mode, status)` (mode coerced to `personal`/`office`). Returns `{mode, status, role}`.

#### Admin (owner only, all via `_require_owner`)

| Method | Path | Body | Behavior |
|---|---|---|---|
| GET | `/admin/overview` | query `token`/Bearer | Dashboard: `{you, role:"owner", db, users:[…(+role each)], counts:{total,active,pending,blocked,office}, office_emails, require_own_keys}`. Users from `db.admin_list_users`, office from `db.office_list`. |
| POST | `/admin/settings` | `SettingsIn{token="", require_own_keys:bool}` | Flips global switch → `db.set_setting("require_own_keys","1"/"0")`. Returns `{require_own_keys}`. |
| POST | `/admin/action` | `AdminActionIn{token="", target_id, action}` | `action`: `approve`/`unblock`→status `active`, `block`→`blocked`, `delete`→`db.delete_user`. 400 `"Database required"` if no DB, 400 `"Unknown action"` otherwise. |
| POST | `/admin/office` | `OfficeEmailIn{token="", email, action}` | `action` `add`→`db.office_add`, `remove`→`db.office_remove`; else 400. Returns `{ok, office_emails}`. |
| POST | `/admin/wipe` | `WipeIn{token=""}` | Testing reset: `db.admin_wipe_users(keep)` deleting everyone except `OWNER_EMAILS ∪ UNLIMITED_EMAILS ∪ db.office_list()`. Returns `{deleted:n, kept:[…]}`. 400 if no DB. |

### WebSocket `/ws/interview` (lines 830–1046)

`ws.accept()`; per-connection locals: `session: Session|None`, `uid`, `started_at` (monotonic), `persisted` flag. Reads JSON text frames in a loop; dispatches on `data["type"]`.

**Inbound message types**

| `type` | Fields | Handling |
|---|---|---|
| `start` | `token`, `keys`, `mode` (default `"interview"`; also `"conversation"`, `"daily"`, `"learning"`), `name`, `role`, `hour` (int 0–23, → `time_of_day` morning/afternoon/evening), `mood`, `resume` (list, daily only — replays up to last 12 turns into `session.transcript`), `seed` (conversation only — pre-answer the greeting) | Auth (if `auth_enabled` and no claims → `auth_error`, break). Blocked-user gate via `db.get_user_flags` (status `blocked` → `error`, break). `resolve_keys` gate (fail → `keys_required`, break) then `set_active_keys(effkeys)`. Loads emotional memory for conversation/interview/daily: `db.get_memory`, `db.recent_summaries(uid,6)`, `_facts_summary`, `db.relationship_stage` → prepends stage tone. Builds `Session(mode, name, role, facts_summary=, mood=, profession=, time_of_day=, level=, daily_context=)`. Then: `daily`→emits `daily_question`; `learning`→emits `ready`; else→emits `status "starting"` then DuSu's opening `ai_text`. |
| `user_text` | `text` | Requires a live session (else `error "send start first"`). `learning`→`status "translating"` then `translation`. `daily`→`status "thinking"` then `daily_turn` (+ `db.save_daily_context`). Else (conversation/interview)→`session.add_user`, `status "thinking"`, `ai_text`; if `session.done`→`interview_done`+`report`+persist; if `session.capped`→`limit`. |
| `end` | — | `interview`→`status "scoring"` + `report`; other modes→`ended`. Then `_persist_session()`. |
| `close` | — | Breaks the loop. |

**Outbound message types**

| `type` | Fields | Meaning |
|---|---|---|
| `ready` | — | Learning mode: client should greet in Hindi. |
| `status` | `msg` | Progress ping: `"starting"`, `"thinking"`, `"translating"`, `"scoring"`. |
| `ai_text` | `text` | DuSu's spoken line (interview/conversation); browser TTS speaks it. |
| `translation` | `hindi`, `text` | Learning mode: echo of their Hindi + the English translation. |
| `translate_error` | — | Learning/daily non-quota failure (present in code; not in header docstring). |
| `daily_question` | `question` | Daily Talk opening Hindi question. |
| `daily_turn` | `hindi`, `english`, `reply`, `tip`, `next_question` | Daily Talk turn result. |
| `report` | `data` | Interview scorecard from `session.build_report()`. |
| `interview_done` | — | Interviewer wrapped up (`session.done`). |
| `limit` | `msg` | Conversation hit its turn cap (`session.capped`). |
| `quota` | `msg` | User's keys hit their limit (`_is_quota` true). |
| `keys_required` | `msg` | BYOK gate failed at `start` — must add own keys. |
| `auth_error` | `msg` | Not signed in (auth enabled). |
| `error` | `msg` | Blocked access, missing session, or generic failure. |
| `ended` | — | Non-interview session ended via `end`. |

**`_persist_session()`** (lines 838–883): one combined LLM pass at session end. No-op if already persisted / no session / no uid / no DB / mode `learning`, or `session.turns <= 0` (prevents 0-turn XP farming). Calls `session.summarize_and_extract()` → `db.add_conversation`, `db.merge_facts`, `db.set_next_hook`; saves cross-mode tail via `db.save_recent_turns` (last 10 turns tagged with mode). Records practice: `daily`→`db.record_practice(seconds, sentences, xp=20)`, else `db.bump_daily_stat`. Grows vocab via `db.add_vocab`. Awards badges: `courage_no_hindi`, `courage_question`, `courage_5min` (>=300s), `courage_first_convo` (conversation/daily). Called on the `end` branch, the interview-done branch, and in `finally` (so a dropped socket still persists).

### Cross-mode memory injection

`_STAGE_TONE` (lines 751–758): dict mapping relationship stage → tone instruction (`Guest`, `Friend`, `Practice Partner`, `Coach`, `Mentor`, `Companion`); prepended to the persona at `start`.

`_facts_summary(facts, summaries)` (lines 761–811): builds the "what DuSu remembers" block injected into the session persona. Emits lines for `nickname`, `profession`, `dream`, `interests`, `facts_learned` (last 5), `events` (last 3), `relationship` traits, `moments` (last 4, with emotion), `achievements` (last 4), `energy_today.value`, `next_hook`, and `recent chats` (summaries). **Cross-mode continuity**: reads `facts["recent_turns"]` (each `{role, content, mode}`), renders the last 6 as "them:/you:" and labels the last mode (`daily`→"Daily Talk (Hindi)", `conversation`→"English Talk", `interview`→"Interview") into a "Where you left off last time… continue THIS thread, do NOT restart" instruction. Closes with a "show you remember; never invent memories" guard.

`_daily_context_str(facts)` (lines 814–827): compact recent-days context from `facts["daily_context"]` — each entry rendered as `date · mood=… · plans=… · weather=… · event=… · note=…`; passed to `Session(daily_context=…)`.

### Related config (`backend/app/config.py`)

`settings` (from `.env`, `pydantic-settings`). Env-backed fields: LLM keys `GEMINI_API_KEY`, `GROQ_API_KEY`, `OPENROUTER_API_KEY`, `GITHUB_TOKEN`; `GOOGLE_CLIENT_ID`, `SESSION_SECRET` (default `"dev-change-me"`); `DATABASE_URL` (empty = stateless); limits `MAX_SESSIONS_PER_DAY=20`, `CONVERSATION_MAX_TURNS=40`, `INTERVIEW_MAX_TURNS=15`; `HOST=0.0.0.0`, `PORT=8000`. `providers()` builds the default fallback chain (gemini → groq → openrouter → github, each with base_url/models/headers/extra); `providers_from(keys)` builds the same chain from BYOK keys `{gemini, groq, openrouter, github}`. OpenRouter headers reference `https://dusu-app-1.onrender.com`.

---

## 4. Database (backend/app/db.py)

The entire persistence layer lives in a single module: `backend/app/db.py`. It uses **SQLAlchemy 2.0 async** (declarative `Mapped[...]` models) against the **self-hosted Postgres** (`db` service in `docker-compose.yml`) via the `asyncpg` driver. The design principle is *graceful degradation*: if no database is configured the app still runs fully, just statelessly.

### 4.1 Connection & the `db_enabled` switch

| Symbol | Definition | Meaning |
|---|---|---|
| `db_enabled` | `bool(settings.database_url)` (line 63) | `True` only when the `DATABASE_URL` env var is non-empty. Empty locally ⇒ `db_enabled = False` ⇒ the app is **stateless** (no user rows, no memory, no progress persisted). |
| `settings.database_url` | Pydantic field `database_url: str = ""` in `backend/app/config.py` (line 24), loaded from `.env` env var **`DATABASE_URL`** | The Postgres connection string — injected by compose as `postgresql://…@db:5432/dusu`. |
| `_engine` | `create_async_engine(...)` — only built when `db_enabled` (lines 64, 67-72); otherwise `None` | Async engine with `pool_pre_ping=True`; `connect_args={"ssl": True}` only when `DATABASE_SSL` is true — compose sets it **false**, since in-network Postgres serves no TLS cert. |
| `_Session` | `async_sessionmaker(_engine, expire_on_commit=False)` — `None` when DB disabled (lines 65, 73) | Session factory used by every public function via `async with _Session() as s:`. |

Every public function that touches the DB opens `async with _Session() as s:`. When `db_enabled` is `False`, `_Session` is `None`; the admin/office/settings helpers guard with `if not db_enabled: return <empty>` first, but the core user functions (`login`, `save_assessment`, etc.) assume the caller only invokes them when the DB is on — the router layer is responsible for that gate.

#### `_normalize_url(url)` (lines 50-60)

Managed providers hand out URLs like `postgresql://user:pass@host/db?sslmode=require&channel_binding=require`. asyncpg needs the `+asyncpg` driver and **rejects** those query params (SSL is supplied via `connect_args` instead). The function:

1. `postgres://` → `postgresql://`
2. `postgresql://` → `postgresql+asyncpg://`
3. Strips everything after `?` (drops `sslmode`, `channel_binding`, etc.)

```python
_normalize_url("postgres://u:p@h/db?sslmode=require")
# -> "postgresql+asyncpg://u:p@h/db"
```

`_now()` (line 76) returns timezone-aware UTC (`dt.datetime.now(dt.timezone.utc)`) and is the default for every timestamp column.

### 4.2 Roadmap / gamification constants (lines 24-30)

| Constant | Value | Purpose |
|---|---|---|
| `LEVEL_LESSON_COUNTS` | `{1:5, 2:5, 3:5, 4:5, 5:5, 6:5, 7:5}` | Lessons per level (mirrors the client CURRICULUM) so the server can detect level completion. |
| `MAX_LEVEL` | `7` | Top of the roadmap. |
| `XP_PER_LESSON` | `20` | XP awarded per first-time lesson completion. |
| `LEVELS_WITH_TEST` | `{1,2,3,4,5,6,7}` | Every level ends with a Boss/Level Test that gates level-up (so `complete_lesson` never auto-levels — `submit_level_test` does). |

Two helper mappers:
- `_start_level(cefr)` (33-35): `{"A0":1,"A1":1,"A2":2,"B1":3,"B2":4}`, default `1`.
- `_daily_goal(practice_time)` (38-47): `"30"→7`, `"20"→5`, `"10"→3`, else `2`.

### 4.3 Models — every table, every column

All models inherit `Base(DeclarativeBase)` (line 80). Primary keys on the per-user tables are the Google `sub` string (`user_id`), so there is one row per Google account per table.

#### `User` — table `users` (lines 84-93)

| Column | Type | Default / notes |
|---|---|---|
| `id` | `String(64)` **PK** | Google `"sub"` claim (falls back to email in `login`). |
| `email` | `String(255)` | `""` |
| `name` | `String(255)` | `""` |
| `picture` | `String(512)` | `""` |
| `created_at` | `DateTime(timezone=True)` | `_now` |
| `last_seen` | `DateTime(timezone=True)` | `_now` (bumped every `login`) |
| `status` | `String(16)` | `"active"` — one of `active` \| `pending` \| `blocked` |
| `mode` | `String(16)` | `"personal"` — one of `personal` \| `office` |

`status` and `mode` were added later; they are back-filled at boot by `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` (see `init_db`).

#### `Profile` — table `profiles` (lines 96-107)

| Column | Type | Default |
|---|---|---|
| `user_id` | `String` **PK**, `ForeignKey("users.id")` | — |
| `onboarded` | `Boolean` | `False` (drives first-run assessment) |
| `goal` | `String(64)` | `""` |
| `comfort` | `String(64)` | `""` |
| `practice_time` | `String(32)` | `""` |
| `level` | `String(8)` | `"A0"` (CEFR) |
| `scores` | `JSONB` | `dict` — skill scores 0-100 |
| `weak_areas` | `JSONB` | `list` |
| `assessed_at` | `DateTime(timezone=True)`, nullable | `None` |

#### `Progress` — table `progress` (lines 110-120)

| Column | Type | Default / notes |
|---|---|---|
| `user_id` | `String` **PK**, FK `users.id` | — |
| `xp` | `Integer`, **indexed** | `0` — leaderboard sort/rank |
| `coins` | `Integer` | `0` |
| `streak_days` | `Integer` | `0` |
| `last_active` | `Date`, nullable | `None` |
| `sessions_today` | `Integer` | `0` |
| `daily_goal` | `Integer` | `5` |
| `badges` | `JSONB` | `list` |
| `journey` | `JSONB` | `dict` |

`journey` is the roadmap doc: `{start_level, current_level, completed:{ "<level>":[lesson_ids] }, lang, sentences_spoken, test_scores:{ "<level>":{best, attempts, passed} }}`.

#### `Memory` — table `memory` (lines 123-128)

One JSONB doc per user — the "emotional layer."

| Column | Type | Default |
|---|---|---|
| `user_id` | `String` **PK**, FK `users.id` | — |
| `facts` | `JSONB` | `dict` |

**`facts` JSON keys actually written by the code** (the whole doc is a schemaless bag; keys below are all the ones the code reads/writes):

| Key | Shape | Written by |
|---|---|---|
| `nickname`, `native_lang`, `profession`, `dream` | strings | `save_about`, `merge_facts` |
| `interests` | dict (merged) | `save_about`, `merge_facts` |
| `facts_learned` | list of strings, dedup, capped `_MAX_FACTS`=40 | `merge_facts` |
| `events` | list of `{type, date, ...}`, capped 20 | `merge_facts` |
| `relationship` | dict (traits, never expire) | `merge_facts` |
| `moments` | list `{text, emotion, created, expires}`, TTL 7d (`_MOMENT_TTL_DAYS`), capped 40 (`_MAX_MOMENTS`) | `_add_moments` via `merge_facts` |
| `achievements` | list `{text, date}`, permanent, capped 60 (`_MAX_ACHIEVEMENTS`) | `_add_achievements` via `merge_facts` |
| `energy_today` | `{date, value}` | `save_checkin` |
| `checkins` | list `{date, mood, energy}`, capped 30 (`_MAX_CHECKINS`) | `save_checkin` |
| `next_hook` | string ≤200 | `set_next_hook`, cleared/consumed by openings |
| `daily_context` | list `{date, mood, plans, weather, events, notes}` — 48h sliding window (today+yesterday) | `save_daily_context` |
| `recent_turns` | list `{role, content≤400, mode}`, last 10 | `save_recent_turns` |
| `baseline` | `{intro_text, date}` | `save_about` |
| `future_me` | `{day1_text, latest_text, latest_date}` | `save_about`, `save_future_me` |
| `daily_stats` | `{ "<date>": {sentences, seconds, sessions, new_words} }`, last ~14d | `bump_daily_stat`, `add_vocab` |
| `total_sentences`, `total_seconds` | ints (lifetime) | `bump_daily_stat` |
| `longest_convo_sec` | int | `bump_daily_stat` |
| `vocab` | list of words, capped 500 (`_MAX_VOCAB`) | `add_vocab` |
| `vocab_total` | int | `add_vocab` |
| `last_confidence` | int (Growth baseline) | `build_growth` |
| `last_letter` | `{date, text}` | `save_letter` |

#### `Conversation` — table `conversations` (lines 131-139)

One row per finished session; an LLM summary DuSu recalls later.

| Column | Type | Default / notes |
|---|---|---|
| `id` | `Integer` **PK**, autoincrement | — |
| `user_id` | `String`, FK `users.id`, **indexed** | — |
| `mode` | `String(32)` | `""` |
| `created_at` | `DateTime(timezone=True)` | `_now` |
| `summary` | `Text` | `""` |

#### `OfficeEmail` — table `office_emails` (lines 1100-1103)

| Column | Type | Notes |
|---|---|---|
| `email` | `String(255)` **PK** | stored lowercased |
| `added_at` | `DateTime(timezone=True)` | `_now` |

#### `Setting` — table `settings` (lines 1144-1147)

Owner toggle key/value store.

| Column | Type | Default |
|---|---|---|
| `key` | `String(64)` **PK** | — |
| `value` | `String(255)` | `""` |

### 4.4 `init_db()` — schema creation + migrations (lines 142-152)

Called at startup. No-op when `db_enabled` is `False`. Inside one `_engine.begin()` transaction:

1. `Base.metadata.create_all` — creates any **missing** tables.
2. `CREATE INDEX IF NOT EXISTS ix_progress_xp ON progress (xp DESC)` — `create_all` won't add an index to an already-existing table, so it's added explicitly (leaderboard sort).
3. `ALTER TABLE users ADD COLUMN IF NOT EXISTS status varchar(16) DEFAULT 'active'`
4. `ALTER TABLE users ADD COLUMN IF NOT EXISTS mode varchar(16) DEFAULT 'personal'`

> **CRITICAL SCHEMA RULE:** `create_all` **only creates missing tables — it NEVER adds a column to a table that already exists.** So new columns on an existing table are invisible in production unless you also add an explicit `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` here (as `status`/`mode` demonstrate). When evolving the schema: **never rely on `create_all` to add a column to an existing table.** Either add an `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` migration in `init_db`, or put the new data in a brand-new table (which `create_all` will create). New JSON fields inside `Memory.facts` / `Progress.journey` need no migration at all since those are schemaless JSONB bags.

### 4.5 Internal helpers

- `_state(user, prof, prog, mem=None)` (155-173) — builds the full client state dict: `{user, status, mode, onboarded, profile{goal,comfort,practice_time,level,scores,weak_areas}, progress{xp,coins,streak_days,sessions_today,daily_goal,badges,journey}, memory}`. Used by `login`/`save_assessment`/`get_state`/leaderboard.
- `_get_or_make_memory(s, user_id)` (488-498) — fetches the `Memory` row **with `with_for_update=True`** (row-lock) so concurrent writers (WS-finally + `/checkin`, two tabs) don't lose-update the full-doc JSONB write; creates the row if missing. Every `facts`-mutating function goes through this and uses `flag_modified(mem, "facts")` so SQLAlchemy detects the in-place JSON change.
- `_prune_moments` / `_add_moments` / `_add_achievements` (448-485) — moment TTL & achievement dedup.
- Leaderboard aliasing: `_ALIAS_ADJ`, `_ALIAS_ANIMAL`, `_alias(user_id)` (367-376) — deterministic playful alias (e.g. `BraveTiger`) from a char-sum hash, so no per-process randomness.
- Companion constants: `_REL_STAGES` (Guest→Companion, 442), `_WORLD_NAMES` (The Village→The Global Stage, 444-445), `_TODAY_CHALLENGES` (per-weekday, 549-557), `_GOALS` / `_goal_card` (611-626).

### 4.6 Public async functions by area

#### Auth / state
| Function | Lines | Behavior |
|---|---|---|
| `login(claims)` | 176-204 | Upsert `User` from Google claims (`sub`/`email`/`name`/`picture`), bump `last_seen`; create `Profile`+`Progress`+`Memory` if new; returns full `_state`. |
| `get_state(user_id)` | 419-427 | Returns `_state` for an existing user or `None` if no `User` row. |

#### Assessment / onboarding
| Function | Lines | Behavior |
|---|---|---|
| `save_assessment(user_id, data, lang="en")` | 207-242 | Persist goal/comfort/practice_time/level/scores/weak_areas, set `onboarded=True`+`assessed_at`; **seed** `Progress.journey` from `_start_level`, set `daily_goal` from `_daily_goal`. |
| `save_about(user_id, about)` | 755-779 | Store onboarding identity facts (nickname/native_lang/profession/dream/interests) + Day-1 `future_me.day1_text` & `baseline.intro_text`. |

#### Progress / XP / streak / badges / lessons / vocab
| Function | Lines | Behavior |
|---|---|---|
| `complete_lesson(user_id, level, lesson_id, lesson_type="")` | 245-313 | First-time lesson → +`XP_PER_LESSON`, `sentences_spoken`++, daily count & streak; level-up **only if the level is not in `LEVELS_WITH_TEST`**; awards `first_lesson`/`first_converse`/`streak_7`/`sentences_100`/`level_up`. Returns `{progress, leveled_up, new_badges}`. |
| `submit_level_test(user_id, level, score)` | 316-362 | Records attempt into `journey.test_scores`; **pass = score≥70**; unlocks next level if `level==current_level`; awards `level_up` and `courage_confident` (≥90). Returns `{progress, leveled_up, new_badges, passed}`. |
| `record_practice(user_id, seconds=0, sentences=0, xp=20)` | 905-925 | A Daily/Talk session = practice: +xp, streak, `sessions_today`++, then folds into `bump_daily_stat`. |
| `bump_daily_stat(user_id, sentences=0, seconds=0)` | 928-948 | Updates `daily_stats[today]`, `longest_convo_sec`, lifetime `total_sentences`/`total_seconds`. |
| `add_vocab(user_id, words)` | 951-974 | Adds new alpha words (≥2 chars) to `vocab` (cap 500), bumps `vocab_total` and `daily_stats[today].new_words`. |
| `award_badges(user_id, ids)` | 987-1002 | Adds badge ids not already present; returns newly-added. |
| `leaderboard(me_id, limit=20)` | 379-416 | Top-N by all-time `xp` (aliased), plus caller's own row+rank (via `COUNT(xp > mine)`). |
| `save_future_me(user_id, text)` | 1005-1018 | Sets `future_me.day1_text` (if unset) + `latest_text`/`latest_date`. |
| `save_letter(user_id, text)` | 977-984 | Stores `last_letter = {date, text}`. |

#### Memory / facts
| Function | Lines | Behavior |
|---|---|---|
| `get_memory(user_id)` | 501-507 | Returns `facts` dict, pruning expired moments first. |
| `merge_facts(user_id, facts, events)` | 782-817 | Merge LLM-extracted identity/interests/notes(`facts_learned`)/relationship/moments/achievements and dedup events. |
| `set_next_hook(user_id, hook)` | 820-832 | Store/clear `next_hook` (≤200 chars) — the "promise for next time." |
| `save_checkin(user_id, mood, energy="")` | 864-877 | Upsert today's checkin + set `energy_today`. |

#### Companion / recommendations (derived, read-mostly)
| Function | Lines | Behavior |
|---|---|---|
| `relationship_stage(user_id)` | 510-524 | Internal Guest→Companion stage from session count + days (never shown). |
| `build_companion_context(user_id)` | 527-546 | Identity + relationship + recent moments/achievements + energy + stage + world + level + next_hook. |
| `build_growth(user_id)` | 560-607 | Confidence composite (persists `last_confidence`), vocabulary, streak, transformation timeline, dream %. |
| `build_opening(user_id)` | 629-646 | DuSu's memory-aware first line (next_hook → last summary → achievement → moment → stage default). |
| `build_recommendations(user_id)` | 649-705 | Ranks intent → 3 goal cards (primary carries a "why"). |
| `build_today(user_id)` | 708-743 | The single dynamic "today" card (story/streak/moment/celebrate/weekday-challenge). |

#### Conversations (recent summaries / turns)
| Function | Lines | Behavior |
|---|---|---|
| `add_conversation(user_id, mode, summary)` | 856-861 | Insert one `Conversation` row (skips empty summary). |
| `recent_summaries(user_id, limit=3)` | 746-752 | Latest N non-empty summaries, newest first. |
| `save_recent_turns(user_id, turns)` | 835-853 | Store last 10 raw turns (`role`/`content≤400`/`mode`) into `facts.recent_turns` for cross-mode thread continuity. |

#### Daily context
| Function | Lines | Behavior |
|---|---|---|
| `save_daily_context(user_id, ctx)` | 880-902 | Merge today's mood/plans/weather/note/events into `facts.daily_context`, keeping only today + yesterday (48h window). |

#### Admin (owner dashboard) — all guard `if not db_enabled`
| Function | Lines | Behavior |
|---|---|---|
| `admin_list_users()` | 1022-1058 | Full per-user rows (identity, status/mode, level/goal, xp/streak, sessions_today/daily_goal, total_sessions from `Conversation` count, total_minutes, words, `daily_stats`), ordered by `last_seen desc`. |
| `set_user_status(user_id, status)` | 1061-1070 | Set `status` ∈ {active, pending, blocked}. Returns bool. |
| `set_user_mode(user_id, mode, status=None)` | 1073-1084 | Set `mode` ∈ {personal, office}, optional status. Returns bool. |
| `get_user_flags(user_id)` | 1087-1096 | Cheap `{status, mode}` for the access gate (defaults `active`/`personal` when DB off or user missing). |
| `admin_wipe_users(keep_emails)` | 1170-1185 | Delete every user (+ Conversation/Memory/Progress/Profile) whose lowercased email is **not** in `keep_emails`. Owner test reset. Returns count. |
| `delete_user(user_id)` | 1188-1199 | Delete a single user + all their child rows. |

#### Office allowlist & settings — all guard `if not db_enabled`
| Function | Lines | Behavior |
|---|---|---|
| `office_list()` | 1106-1111 | All allowlisted emails, newest first. |
| `office_has(email)` | 1114-1119 | Membership check (lowercased). |
| `office_add(email)` | 1122-1129 | Insert if valid (`@` present) and not present. |
| `office_remove(email)` | 1132-1140 | Delete if present. |
| `get_setting(key, default="")` | 1150-1155 | Read a `Setting` value (returns `default` when DB off/missing). |
| `set_setting(key, value)` | 1158-1167 | Upsert a `Setting`. |

---

## 5. LLM Brain, Providers & Prompts

DuSu's "brain" is a single **OpenAI-compatible chat-completions client that fans out across a chain of free LLM providers**. There is no local model and no vendor SDK beyond `openai` — every provider (Gemini, Groq, OpenRouter, GitHub Models) speaks the OpenAI Chat Completions shape, so one `AsyncOpenAI` client per provider (differing only in `base_url` + `key` + `default_headers`) drives them all. Speech (STT/TTS) is entirely browser-side; the model only ever sees and emits **text**.

### 5.1 Files at a glance

| File | Role |
|---|---|
| `backend/app/config.py` | `Settings` (pydantic-settings): env keys, usage caps, and the two chain builders `providers()` / `providers_from(keys)`. |
| `backend/app/providers/base.py` | `LLMProvider` `Protocol` (structural interface: `next_question`, `score`). App depends on this, never a concrete vendor. |
| `backend/app/providers/openrouter_provider.py` | The actual engine: chain walker `_complete`, cooldown logic, `_extract_json`, per-request routing (`_active_chain` / `set_active_keys`), and the `OpenRouterLLM` class with `next_question` / `translate` / `generate` / `assess` / `score`. |
| `backend/app/providers/__init__.py` | Wiring point. Instantiates `llm = OpenRouterLLM()` and exports it. **There is no `llm.py`** — `from ..providers import llm` resolves to this singleton. |
| `backend/app/interview/engine.py` | `Session` class: per-session state + turn logic for all four modes. |
| `backend/app/interview/prompts.py` | All system prompts + `interviewer_system()` / `conversation_system()` builders and the `COMPETENCIES` / `DUSU_PERSONA` constants. |
| `backend/app/main.py` | HTTP/WS endpoints that call `llm.*` directly for one-shot tasks (level test, greeting, letter, lesson eval) and set per-request keys. |

### 5.2 Settings / config (`config.py`)

Loaded once from `.env` (`SettingsConfigDict(env_file=".env", extra="ignore")`); the module-level singleton is `settings = Settings()`.

**Env-var fields** (empty string default → skipped in the chain):

| Field / env var | Purpose |
|---|---|
| `gemini_api_key` | Google Gemini (OpenAI-compat endpoint) key |
| `groq_api_key` | Groq key |
| `openrouter_api_key` | OpenRouter key |
| `github_token` | GitHub Models inference key |
| `google_client_id` | Google Sign-In |
| `session_secret` (default `"dev-change-me"`) | session signing |
| `database_url` (default `""`) | Postgres; supplied by compose. Empty = app runs stateless |
| `host` (`0.0.0.0`), `port` (`8000`) | server bind |

**Usage caps** (protect the shared free quota):

| Field | Default | Meaning |
|---|---|---|
| `max_sessions_per_day` | `20` | per user; resets daily |
| `conversation_max_turns` | `40` | free chat gently wraps up |
| `interview_max_turns` | `15` | hard cap (interview self-ends ~8 exchanges) |

### 5.3 The FREE provider failover chain — `settings.providers()`

Returns a list of provider dicts **in fallback order**. Each dict: `name`, `base_url`, `key`, `models` (tried in order), `headers`, `extra` (per-provider request body merged as `extra_body`). Empty keys are skipped, so the live chain is whatever subset of keys is configured.

| Order | name | base_url | env key | models (in order) | headers / extra |
|---|---|---|---|---|---|
| 1 | `gemini` | `https://generativelanguage.googleapis.com/v1beta/openai/` | `gemini_api_key` | `gemini-flash-latest`, `gemini-flash-lite-latest` | `extra={}` — **Gemini's OpenAI-compat rejects `reasoning_effort` (400), so extra must stay empty** |
| 2 | `groq` | `https://api.groq.com/openai/v1` | `groq_api_key` | `llama-3.3-70b-versatile`, `llama-3.1-8b-instant` | `extra={}` |
| 3 | `openrouter` | `https://openrouter.ai/api/v1` | `openrouter_api_key` | `openai/gpt-oss-20b:free`, `nvidia/nemotron-3-super-120b-a12b:free` | `headers={HTTP-Referer: https://dusu-app-1.onrender.com, X-Title: DuSu}`, `extra={"reasoning":{"exclude":True,"effort":"low"}}` |
| 4 | `github` | `https://models.github.ai/inference` | `github_token` | `openai/gpt-4o-mini`, `meta/Llama-3.3-70B-Instruct` | `extra={}` |

Note in code: `meta-llama/llama-3.3-70b-instruct:free` was dropped from OpenRouter (now paid-only → 404).

### 5.4 BYOK / "Office mode" chain — `settings.providers_from(keys)`

Builds the **same** base_urls / models / headers / order as `providers()`, but from caller-supplied keys instead of env. Input `keys` is a dict `{gemini, groq, openrouter, github}`; each value is coerced to a stripped string (`str(vv or "").strip()`) and missing/empty keys are skipped. Used both to build a per-request chain and (in `main.py:267`) to validate the shape of user-provided keys.

### 5.5 Per-request routing — `_active_chain` contextvar + `set_active_keys(keys)`

In `openrouter_provider.py`:

```python
_active_chain: ContextVar[list | None] = ContextVar("_active_chain", default=None)

def set_active_keys(keys: dict | None) -> None:
    chain = settings.providers_from(keys) if keys else None
    _active_chain.set(chain or None)
```

- `contextvars` are per-task, so **each WebSocket connection / HTTP request is isolated** — one user's BYOK keys never leak into another's request.
- `_complete` picks the chain with `chain = _active_chain.get() or settings.providers()` — Office/BYOK keys if set for this request, otherwise the default env chain.
- `main.py` calls `set_active_keys(...)` at the top of every key-scoped endpoint (`leveltest_gen` line 439, `assess` line 466, `greeting` line 539, `letter` line 587, `lesson eval` line 649, `leveltest grade` line 698, and the WS handler line 911) before invoking `llm.*`.

### 5.6 The chain walker — `_complete(messages, max_tokens)`

Core loop that every helper funnels through. Behavior:

- **Clients are cached** per provider name in `_clients` (`_client(p)` lazily builds `AsyncOpenAI(api_key, base_url, default_headers)`).
- **Cooldown map** `_cooldown: {provider_name -> skip-until-epoch}`. `_mark_cooldown(name, err)` sets a **1800s (30 min)** skip if the error text looks like a daily/quota exhaustion (`"day"`, `"quota"`, `"free_tier"`, `"free-models"`), else **90s**.
- Two passes: `for ignore_cd in (False, True)` — first pass skips providers still on cooldown; if **every** provider is cooling down (nothing attempted), the second pass tries them anyway rather than failing.
- For each provider it walks `p["models"]` in order, calling `client.chat.completions.create(model, messages, max_tokens, temperature=0.7, extra_body=p["extra"])`.
- On a non-empty `resp.choices[0].message.content`, returns the stripped text.
- On exception: if the error string contains `429/rate/quota/exceed/exhaust` → `_mark_cooldown` the whole provider and `break` (skip its remaining models); any other error → `continue` to the next model.
- If nothing answers: `raise RuntimeError(f"all providers/models unavailable: {last_err}")`.

### 5.7 Robust JSON extraction — `_extract_json(text)`

Hardened parser used by every JSON-returning helper (`assess`, `score`), because models don't always emit clean JSON:

1. Strips leading/trailing whitespace.
2. **Strips ```` ```json ```` / ```` ``` ```` code fences** via regex (`^```(?:json)?\s*` and `\s*```$`).
3. `json.loads` the cleaned text.
4. On `JSONDecodeError`, greedily regexes the first `\{.*\}` block (`re.DOTALL`, to the last closing brace) and retries.
5. On total failure returns a sentinel `{"error": "scoring_parse_failed", "raw": text[:500]}` — callers check `d.get("error")` (e.g. `leveltest_gen`).

### 5.8 `llm` helper methods (`OpenRouterLLM`)

| Method | Signature | max_tokens | Returns | Notes |
|---|---|---|---|---|
| `next_question` | `(system, transcript)` | **250** | `str` | Builds `[{system}, *transcript]`. **If transcript has no user turn**, appends a seed user turn `"Let's begin. Greet me and ask your first question."` — some providers (Gemini) reject a system-only request, and DuSu speaks first. |
| `translate` | `(system, text)` | **120** | `str` | `[{system}, {user: text}]`. |
| `generate` | `(system, prompt, max_tokens=500)` | 500 default | `str` | Free-form prose (weekly letters, summaries). Raw text. |
| `assess` | `(system, payload, max_tokens=700)` | **700 default** | `dict` | Appends `"\n\nReturn ONLY the JSON object."` to payload, then `_extract_json`. |
| `score` | `(system, transcript)` | **1200** | `dict` | Flattens transcript to `role: content` lines, appends `"\n\nReturn ONLY the JSON object."`, then `_extract_json`. |

**The 700→1100 daily fix:** `assess` defaults to 700 tokens, but `Session.daily_turn` overrides it with `max_tokens=1100` (`engine.py:84`). The daily reply must fit the full friend-reply plus the whole JSON payload (`english` + `reply_hindi` + `next_question_hindi` + `tip` + `mood` + `context`) — at 700 it truncated mid-JSON and produced an empty reply.

### 5.9 `Session` class (`interview/engine.py`)

- `END_MARKER = "INTERVIEW_COMPLETE:"`
- `MODES = ("interview", "conversation", "learning", "daily")`

**Constructor** `__init__(mode, name, role, facts_summary="", mood="", profession="", time_of_day="", level="", daily_context="")`:
- `mode` falls back to `"interview"` if not in `MODES`; `name` defaults to `"there"`, `role` to `"general"`.
- Builds the static system prompt per mode: `interview` → `interviewer_system(name, role, facts_summary, mood)`; `conversation` → `conversation_system(name, facts_summary, mood)`; **`learning` and `daily` get `self.system = ""`** (daily builds its prompt per-turn via `assess`; learning is one-shot `translate`).
- State: `self.transcript: list[dict]` (`{role: "user"|"assistant", content}`), `self.done=False`, `self.capped=False` (conversation hit cap), `self.turns=0` (user turns so far).

**Methods:**

| Method | What it does |
|---|---|
| `add_user(text)` | Appends `{role:"user", content:text}` to transcript, `turns += 1`. |
| `next_ai_turn()` | Calls `llm.next_question(self.system, transcript)`. **Interview:** if `END_MARKER` in the raw reply → `done=True`, spoken = text after the marker (or a default closer); else if `turns >= interview_max_turns` (15) → `done=True` with a "that's all the questions" wrap. **Conversation:** if `turns >= conversation_max_turns` (40) → `capped=True` with a "let's pause here" line. Appends the assistant line and returns `spoken`. |
| `translate(text)` | Learning mode: `llm.translate(TRANSLATE_SYSTEM, text)` → Hindi/Hinglish → spoken English. |
| `daily_turn(answer, first=False)` | Daily Companion. Builds a text `payload` with **LEARNER FACTS**, `profession`, `time_of_day`, `english_level` (defaults `A1`), recent `daily_context`, and the `conversation so far`. If `first=True`, instructs the model to open warmly and leave english/praise empty; else appends `learner just said (in Hindi/Hinglish): {answer}`. Calls `llm.assess(DAILY_TURN_SYSTEM, payload, max_tokens=1100)`. When not first, appends the user answer (`turns += 1`); then stores `reply = data["reply_hindi"] or data["next_question_hindi"]` as the assistant turn. Returns the full `data` dict (`english`, `reply_hindi`, `next_question_hindi`, `tip`, `mood`, `context`). The convo-so-far in the payload is how it **resumes**. |
| `build_report()` | Interview only (else `{}`): `llm.score(SCORER_SYSTEM, transcript)`. |
| `summarize_and_extract()` | ONE call at session end → summary + facts + events + signals. Returns `{}` for learning mode or if no user turn exists. Flattens transcript and calls `llm.assess(SESSION_MEMORY_SYSTEM, convo)`, swallowing exceptions to `{}`. |

### 5.10 Prompts (`interview/prompts.py`)

Shared building blocks: `COMPETENCIES` (list: `self_introduction`, `role_motivation`, `project_depth`, `communication`, `strengths_weakness`); `DUSU_PERSONA` (the consistent patient/warm/never-judging coach voice, prepended to interview + conversation prompts); `_memory_block(facts_summary, mood)` (compact "what you remember about this learner" + mood-adjustment text injected into both builders).

| Prompt | Used by | Output shape | What it produces |
|---|---|---|---|
| `interviewer_system(name, role, facts_summary, mood)` | `Session` (interview) | plain text | DUSU_PERSONA + rules for a spoken mock interview: one question at a time, <2 sentences, adapt to answers, cover the 5 competencies, **no grammar correction during**, end with a line starting exactly `INTERVIEW_COMPLETE:` after ~6-8 exchanges. |
| `conversation_system(name, facts_summary, mood)` | `Session` (conversation) | plain text | DUSU_PERSONA + rules for warm spoken English chat: 1-2 sentences, react + one open follow-up, follow their interests, **never end / never say goodbye**, no lecturing, read the feeling behind words, continue the one ongoing cross-mode relationship thread from memory. |
| `GREETING_SYSTEM` | `main.py:561` via `llm.next_question` (payload = memory JSON) | plain text (≤45 words) | ONE short spoken greeting in **Devanagari-mixed Hinglish** (~55% Hindi Devanagari + Latin English so TTS pronounces it) — greet by name, exactly one real memory callback, one encouragement, place them in their journey, end with one open question. |
| `SESSION_MEMORY_SYSTEM` | `Session.summarize_and_extract` via `assess` | JSON | Durable memory extraction: `summary`, `facts` (`interests`, `profession`, `dream`, `notes`, `relationship`, `moments`, `achievements`), `events[]`, `no_hindi` bool, `asked_question` bool, `next_hook` string. Only keys actually found. |
| `DAILY_TURN_SYSTEM` | `Session.daily_turn` via `assess(max_tokens=1100)` | JSON | The Daily Companion "close friend" reply. Internal reasoning about dominant/hidden emotion, then a 50-90-word Hinglish (Latin script) reply in a 6-step shape ending in exactly one follow-up question. Returns `english` (learner's line translated to natural English), `reply_hindi`, `next_question_hindi`, `tip`, `mood`, `context{plans,weather,events[]}`. Hard rules: use their real name (never "bhai/yaar"), forbidden filler phrases, never re-ask. |
| `LETTER_SYSTEM` | `main.py:618` via `llm.generate(max_tokens=350)` | plain text | A warm 4-6 line weekly mentor note starting `Hi <name>,`, referencing real facts/progress; may add one Hindi (Latin) line for Hindi beginners. |
| `TRANSLATE_SYSTEM` | `Session.translate` via `llm.translate` | plain text (one sentence) | Hindi/Hinglish → natural spoken English, output only the English sentence (no quotes/explanation), meaning-based not literal. Includes few-shot examples. |
| `ASSESS_SYSTEM` | `main.py:479` via `assess` (onboarding level test) | JSON | CEFR level assessment from MCQ answers + 4 spoken task transcripts (intro/repeat/think/open). Scores 6 skills 0-100 (`confidence`, `pronunciation`, `listening`, `vocabulary`, `grammar`, `thinking`), picks `level` (A0-B2), `weak_areas` (≤3), warm `message`. |
| `LESSON_EVAL_SYSTEM` | `main.py:658` via `assess` | JSON | Grades one short spoken lesson answer kindly: `pass` bool, `correct_english`, `feedback` (Hindi Latin if `lang==hi`), `encouragement`. |
| `LEVEL_TEST_SYSTEM` | `main.py:708` via `assess` | JSON | Grades a whole end-of-level test set generously: `score` 0-100, `passed` (≥70), per-item `items[]` (`pass`+`feedback`), warm `message`. (Note: the level-test **questions** are generated dynamically by an inline prompt in `leveltest_gen`, `main.py:440-444`, not by this graded prompt.) |
| `SCORER_SYSTEM` | `Session.build_report` via `llm.score` | JSON | Full interview evaluation: `overall` 0-100, `scores{grammar,fluency,confidence,communication,vocabulary,professionalism}`, `filler_words[]`, `strengths[]` (≤3), `fixes[]` (≤3), `better_answer{question, their_answer, improved}`. |

All JSON prompts explicitly instruct "Return ONLY a JSON object (no markdown)", which pairs with `_extract_json`'s fence-stripping defense in depth.

---

## 6. Frontend — Shell, Auth & Routing (backend/test_client.html)

The entire DuSu web app is **one self-contained file**: `backend/test_client.html` (~4135 lines). There is **no build step, no framework, no bundler, no modules** — a single top `<style>` block, the HTML body (all screens stacked), and one bottom `<script>` running in a single global scope. It is served verbatim by FastAPI.

### 6.1 How it is served (server-side placeholder injection)

`GET /` in `backend/app/main.py` (line 734, `index()`) reads the file and does three literal string replacements before returning `HTMLResponse`:

| Placeholder in HTML | Replaced with | Source |
|---|---|---|
| `__GOOGLE_CLIENT_ID__` | Google OAuth client id | `settings.google_client_id` |
| `__AUTH_ENABLED__` | `true` / `false` (unquoted JS boolean) | `auth.auth_enabled` |
| `__MAX_SESSIONS__` | daily session cap (default `20`) | `settings.max_sessions_per_day` |

In JS these become: `const GOOGLE_CLIENT_ID = "__GOOGLE_CLIENT_ID__";` (line 3826), `const AUTH_ENABLED = __AUTH_ENABLED__;` (line 3827), `const MAX_SESSIONS = Number("__MAX_SESSIONS__") || 20;` (line 3857). Global helper: `const $ = id => document.getElementById(id);` (line 1744). Speech is 100% browser-side (Web Speech API `SpeechRecognition`/`speechSynthesis`); the server only ever receives text. `WS_URL` (line 1743) is derived from `location`: `(https→wss / http→ws) + location.host + "/ws/interview"`.

### 6.2 App-shell CSS (fixed viewport, one scroll region, phone frame)

The shell is a flex column pinned to the viewport height; only the middle `.wrap` scrolls, and `.bnav` is a genuine flex child at the bottom (not `position:fixed`).

```css
body { height:100vh; height:100dvh; display:flex; flex-direction:column;
       overflow-x:hidden; overscroll-behavior-y:none; }          /* line 47 */
.wrap { max-width:440px; width:100%; flex:1 1 auto;
        overflow-y:auto; overflow-x:hidden;                       /* the ONLY scroll region */
        -webkit-overflow-scrolling:touch; margin:0 auto;          /* centered → phone frame on desktop */
        padding: max(24px,env(safe-area-inset-top)) … ; }         /* line 54; notch-safe */
.bnav { flex:0 0 auto; width:100%; max-width:440px; height:76px;  /* line 961; REAL bottom bar */
        margin:0 auto; background:rgba(10,14,26,.94); backdrop-filter:blur(14px);
        border-top:1px solid rgba(255,255,255,.07);
        padding-bottom:env(safe-area-inset-bottom); }
.bnav.hide { display:none; }                                      /* hidden on login/onboarding */
.screen   { display:none; animation:fade .45s ease both; }        /* line 142 */
.screen.on{ display:block; }
```

- The 440px `max-width` + `margin:0 auto` on both `.wrap` and `.bnav` produces a **centered phone-width column** on desktop; on mobile it fills the width. A `@media (max-width:480px)` block (line 60) tightens padding/logo/hero sizes.
- Custom thin scrollbar styling is applied only to `.wrap` (lines 1013–1017, Firefox `scrollbar-*` + WebKit `::-webkit-scrollbar`).
- The notification bar (`.notif`, line 1021) and More sheet (`.msheet`/`.msheet-bg`, lines 1036–1042) are the only `position:fixed` chrome, each also `max-width:440px` and centered with `left:50%; transform:translateX(-50%)`.

### 6.3 Screen system

Every screen is a `<section class="screen">` with a unique id. Exactly one carries `.on` at a time.

| Section id | Purpose | NAV_TAB → tab |
|---|---|---|
| `login` | Google sign-in card (`#gbtn`, `#loginNote`) | (nav hidden) |
| `home` | Hero, Today card, growth strip, mode cards | `home` |
| `keys` | BYOK / Office-mode key entry + verify | `more` |
| `admin` | Owner dashboard (users & activity) | `more` |
| `practice` | Mode picker landing | `practice` |
| `setup` | Interview setup (role/name) | `practice` |
| `learning` | "Learn" voice loop | `practice` |
| `daily` | "Talk about your day" voice loop | `daily` |
| `assessment` | Dynamic level test | (nav hidden) |
| `journey` | Journey/dashboard (also reused as "Profile") | `journey` |
| `leaderboard` | Ranks | `leaderboard` |
| `lesson` | Level-test lesson runner | `practice` |
| `session` | Live conversation/interview voice loop | `practice` |
| `report` | Post-session report | `practice` |

**`show(id)`** (line 1887) is the router:
1. If leaving a live voice screen (`cur ∈ VOICE_SCREENS` and `cur !== id`) it calls **`stopAllVoice()`** first, so DuSu never keeps talking on another tab.
2. Removes `.on` from all `.screen`, adds it to `$(id)`.
3. On `home`: hides `#moreHome`, re-renders `renderHomeJourney()` + `renderHomeExtras2()`.
4. Calls `syncNav(id)`.

```js
const VOICE_SCREENS = new Set(["session","daily","learning"]);   // line 1872
function currentScreen(){ const el=document.querySelector(".screen.on"); return el?el.id:""; }
```

**`stopAllVoice()`** (line 1875) is the teardown: `running=false; aiSpeaking=false`, stops conversation STT (`stopListening()`), stops daily STT (`drec.stop()`), `speechSynthesis.cancel()`, stops face/assistant lip-sync, `dMicActive(false)`, and closes the WebSocket (`ws.onclose=null; ws.close(); ws=null` — the server persists state on disconnect). A `visibilitychange` listener (line 1910) also calls `stopAllVoice()` when the tab is hidden while a voice loop is running.

**`syncNav(id)`** (line 1904) toggles `.bnav.hide` for `login`/`assessment`, then looks up `NAV_TAB[id]` and lights the matching `.btab.active`:

```js
const NAV_TAB = { home:"home", journey:"journey", daily:"daily", practice:"practice",
  learning:"practice", session:"practice", setup:"practice", lesson:"practice", report:"practice",
  leaderboard:"leaderboard", profile:"more", keys:"more", admin:"more" };   // line 1901
```

**Bottom-nav wiring** (line 1915) — six `.btab[data-tab]` buttons (`home`, `journey`, `daily`, `practice`, `leaderboard`, `more`):
- `home → goHome()`, `journey → openJourney()`, `daily → startDaily("speak")`, `practice → show("practice")`, `leaderboard → openLeaderboard()`.
- `more` opens the sheet via `toggleSheet(true)`, and reveals the owner-only Dashboard row (`#mrowAdmin`) only when `userState.role === "owner"`.

**More sheet** (`#msheet` / `#msheetBg`, HTML line 1721): `toggleSheet(o)` (line 1913) toggles `.on`. Rows are `.mrow[data-more]` (handler line 1928): `leaderboard`, `profile` (→ `openJourney()`, reused as Profile), `leveltest` (→ `startAssessment()`), `keys` (→ `show("keys"); loadKeysUI()`), `admin` (→ `openAdmin()`), `signout` (→ `logout()`). Tapping the backdrop closes it and re-syncs nav to home/practice.

### 6.4 Auth (Google Sign-In + HMAC token)

Config/state globals (lines 3826–3830): `GOOGLE_CLIENT_ID`, `AUTH_ENABLED`, `authToken = localStorage.getItem("dusu_token")`, `authUser = JSON.parse(localStorage.getItem("dusu_user"))`, `userState = null`.

**`onGoogle(resp)`** (line 4075) — the GIS callback. POSTs `{credential}` to **`/auth/google`**, then on success:
- `authToken = d.token`, persists `dusu_token`, `dusu_user`, `dusu_onboarded`.
- Seeds `userState` from the response, calls `applyUser(d.user)`.
- Always `show("home")` immediately, then `refreshMe()`. Brand-new users (`d.onboarded === false`) rely on `refreshMe()` → `routeAfterLogin()` to reach the level test; returning users additionally get `speakWelcome()` (needs the sign-in click as the audio gesture).

**`applyUser(u)`** (line 3832): reveals `#hdrRight`, hides tagline, fills `#uName`, and swaps Google `#uAvatar` photo vs `#uInit` initials (`av.onerror → useInit`). Also prefills the interview name field, `setWelcome()`, `refreshUsage()`.

The **session token is HMAC-signed server-side** (`backend/app/auth.py`, `make_session`, line 59): `base64url(JSON payload).base64url(HMAC-SHA256(payload, SECRET))` with a 30-day `exp`. It is self-contained (no DB lookup); `read_session()` recomputes the signature with `hmac.compare_digest` and checks `exp`. The client just stores the opaque string in `dusu_token` and sends it as `Authorization: Bearer <token>` (for `/me`) or inside JSON/WS payloads as `token`.

### 6.5 The deterministic login gate

**`routeAfterLogin()`** (line 4045) is the single source of truth for "which screen after login", in strict priority order:

```
1. needsKeys() && !hasOwnKeys()   → force Office mode, show("keys"), loadKeysUI(),
                                     status "🔒 Add your own free API keys (at least 2) to start."
2. userState.onboarded === false  → startAssessment()      (level/test not done)
3. otherwise                      → show("home") + setWelcome() + renderHomeJourney()
```

**`initAuth()`** (line 4101, called once at the bottom): if `!AUTH_ENABLED` it skips login (`show("home")`, dev fallback). If a cached `authToken`+`authUser` exist it: `applyUser`, restores cached `userState` from `dusu_state` **before first paint**, optimistically routes via `routeAfterLogin()` from cached state, then calls `refreshMe()` to re-confirm. Otherwise `show("login")`. Finally it polls until `google.accounts.id` is ready, then `initialize({client_id, callback:onGoogle})` and renders the button into `#gbtn`.

**`refreshMe()`** (line 4060): `fetch("/me", {cache:"no-store", Authorization:Bearer})`. On `401` → `logout()` (real sign-out). On success it sets `userState`, persists `dusu_onboarded` and the whole state to `dusu_state`, then calls `routeAfterLogin()`. On network failure it returns `null` and keeps the cached home (never strands the user offline).

**`logout()`** (line 4034): clears `authToken`/`authUser`, removes `dusu_token`, `dusu_user`, `dusu_state`, `dusu_letter`, `dusu_daily_resume`, `dusu_keys_ok`, closes the WS, disables Google auto-select, `show("login")`.

### 6.6 Every localStorage key

| Key | Written by | Meaning |
|---|---|---|
| `dusu_token` | `onGoogle` | HMAC session token; sent as Bearer / `token`. Cleared on logout. |
| `dusu_user` | `onGoogle` | Cached Google user `{sub,email,name,picture}` for instant boot. Cleared on logout. |
| `dusu_onboarded` | `onGoogle`, `refreshMe`, assessment finish | `"true"`/`"false"` — has the level test been completed. |
| `dusu_state` | `refreshMe`, assessment finish | Full `/me` state JSON (today, growth, opening, recommendations) cached for zero-wait first paint. Cleared on logout. |
| `dusu_letter` | `openJourney`/letter fetch (line 3417) | Cached "letter to future self" text. Cleared on logout. |
| `dusu_daily_resume` | `saveDailyResume` (line 2621) | `{date, turns:last12, lastQuestion}` to resume the Daily chat; only reused if ≤ 2 days old, else discarded. Cleared on logout. |
| `dusu_office_keys` | key verify (line 1985) | JSON of BYOK keys `{gemini, openrouter, github, groq}`. |
| `dusu_usemode` | mode toggle / gate | `"personal"` (our keys) or `"office"` (user's own keys). Default `"personal"`. |
| `dusu_keys_ok` | key verify | `"1"` once ≥2 keys passed `/keys/verify`. Removed whenever a key input is edited (line 1968) and on logout. |
| `dusu_voice` | voice `♀/♂` toggle (line 2400) | Preferred TTS gender. **Note: written but never read back on init** — `voiceGender` always defaults to `"female"` (line 2370). |
| `dusu_usage` | `usageInc` (line 3871) | `{d:YYYY-MM-DD, n}` daily session counter for the free-tier cap. |
| `dusu_think` | `pushThink` (line 3950) | Rolling array (last 30) of "thinking speed" seconds → home growth chip. |

### 6.7 BYOK / Office-mode helpers

All defined around lines 1746–1773. "Office mode" means the user supplies their own free AI keys; "Personal" uses the app's keys.

| Function | Line | Behavior |
|---|---|---|
| `officeKeys()` | 1747 | `{}` in Personal mode; else parsed `dusu_office_keys`. This is the object sent to the server on every start/lesson/report request (see call sites below). |
| `officeAllowed()` | 1752 | True if `userState.office_allowed \|\| free_access \|\| role === "owner"/"unlimited"` — i.e. this user may use **our** keys. |
| `savedKeys()` | 1753 | Parsed `dusu_office_keys` (regardless of mode). |
| `keyCount()` | 1754 | Count of non-empty saved key values. |
| `keysVerified()` | 1755 | `dusu_keys_ok === "1"`. |
| `hasOwnKeys()` | 1756 | `keyCount() >= 2 && keysVerified()` — the hard requirement. |
| `needsKeys()` | 1762 | `userState.require_own_keys && !officeAllowed()` — global BYOK switch is ON and this user isn't free-access. |
| `mustAddKeys()` | 1763 | `needsKeys() && !hasOwnKeys()`. |
| `guardKeys()` | 1765 | If `mustAddKeys()`: force Office mode, `show("keys")`, `loadKeysUI()`, set lock status, return `true` (blocked). Called at the top of `chooseMode()` (2088), `startDaily()` (2649), `startAssessment()` (2913). |
| `showNotif(msg)` | 1759 | Fills `#notifTxt`, shows the fixed `#notifBar`, auto-hides after 10s. Triggered on WS `"quota"` message (line 2351) and HTTP `429` (lines 3036/…). |

**Keys UI**: `loadKeysUI()` (1947) fills the four inputs (`#kGemini #kOpenrouter #kGithub #kGroq`) from `dusu_office_keys`, and when `needsKeys()` hides the "Personal" option and shows the lock note. `#verifyKeys` (1971) POSTs `{token, keys}` to **`/keys/verify`**; per-key status shows ✅/❌; on **≥2 working keys** it saves `dusu_office_keys`, sets `dusu_usemode="office"` + `dusu_keys_ok="1"`, and calls `routeAfterLogin()` to continue; otherwise it removes `dusu_keys_ok` and stays locked. Editing any input clears `dusu_keys_ok` (must re-verify). Mode toggles (`#modePersonal`/`#modeOffice`, lines 1965–1966) also POST to **`/mode`** via `postMode()`.

`officeKeys()` is threaded into the server on: WS `start` (conversation line 2285, learning 2566, daily 2671), and HTTP bodies for report/lesson/level endpoints (lines 2194, 3030, 3088, 3584, 3782).

### 6.8 Service worker (PWA) & versioning

Registered at the very end of the script (line 4128): on `window load`, `navigator.serviceWorker.register("/sw.js")`. The SW file is `backend/sw.js`, served by `main.py` at `GET /sw.js` (line 112).

- **Cache name / version**: `const CACHE = "dusu-v5";` (line 5). Bump this string to invalidate the cache on deploy; `activate` deletes every cache key that isn't the current `CACHE`.
- **Shell precache**: `["/", "/logo.png", "/manifest.webmanifest"]`.
- **Strategy**: navigations are **network-first** (always fetch fresh HTML so new deploys appear, falling back to cached `/` offline); static assets are **cache-first** then network. `install` calls `skipWaiting()`, `activate` calls `clients.claim()`.
- **Never cached** (returned early, always live): any path starting with `/ws`, `/auth`, `/me`, `/health`, `/lesson`, `/level`, `/assessment`, `/admin`, `/keys`, `/mode`, `/.well-known`, and all non-GET methods. (`/me` was explicitly excluded to stop a stale `onboarded` flag being served forever.)

---

## 7. Frontend — Flows & Screens (backend/test_client.html)

The entire client is a **single 4135-line file** `backend/test_client.html` — one inline `<style>` block and one inline `<script>`, no build step, no framework. It is served by the FastAPI backend, which substitutes three placeholders at serve time: `__MAX_SESSIONS__` (line 3857), `__GOOGLE_CLIENT_ID__` (3826), `__AUTH_ENABLED__` (3827). Speech is 100% browser-side (Web Speech API — `SpeechRecognition`/`speechSynthesis`); the server only ever exchanges **text** over one WebSocket: `WS_URL = (https?→wss/ws)://<host>/ws/interview` (line 1743).

### 7.0 App shell, screens & navigation

Every view is a `<section class="screen">`; exactly one carries `.on`. `show(id)` (1887) removes `.on` from all and adds it to `#id`. **Crucially, if the screen being left is in `VOICE_SCREENS = {"session","daily","learning"}` (1872), `show()` calls `stopAllVoice()` first** so the AI never keeps talking on another tab.

| `<section id>` | Line | Purpose |
|---|---|---|
| `login` | 1098 | Google Sign-In (`#gbtn`, `#loginNote`) |
| `home` | 1109 | Hero + living DuSu face + Companion Moment + `#moreHome` extras |
| `keys` | 1259 | Personal/Office mode + BYOK key form |
| `admin` | 1283 | Owner dashboard (`#adminBody`) |
| `practice` | 1292 | 3 headed practice pills |
| `setup` | 1344 | Interview role entry (`#role`) |
| `learning` | 1397 | Translate mode (Hindi→English) |
| `daily` | 1433 | Daily Talk companion |
| `assessment` | 1522 | First-time level test (`#assessStep`, `#assessBar`) |
| `journey` | 1533 | Roadmap/dashboard |
| `leaderboard` | 1555 | Global ranks |
| `lesson` | 1571 | Curriculum think/speak lesson |
| `session` | 1605 | Conversation + Interview voice loop (`#orb`, `#feed`) |
| `report` | 1700 | Scored interview report |

**Bottom nav** `#bnav` (1730) has tabs `home / journey / daily / practice / leaderboard / more`. `NAV_TAB` (1901) maps each screen to the tab that lights up (e.g. `session`→`practice`). `syncNav(id)` (1904) hides the nav only on `login`/`assessment`. Tab handlers (1915): home→`goHome()`, journey→`openJourney()`, daily→`startDaily("speak")`, practice→`show("practice")`, leaderboard→`openLeaderboard()`, more→opens the `#msheet` sheet (`toggleSheet`) and reveals `#mrowAdmin` only when `userState.role === "owner"`. The **More sheet** rows (1928): profile→`openJourney()`, keys→`show("keys")+loadKeysUI()`, leveltest→`startAssessment()`, admin→`openAdmin()`, signout→`logout()`.

Global voice state (1778-1782): `ws, recog, running=false, currentMode="conversation", aiSpeaking=false, lastReport, srFails=0, LISTEN_DELAY=450`.

### 7.a Level test / assessment (first-time onboarding)

Entry: `startAssessment()` (2911). Guards: `if(aActive) return` (double-`routeAfterLogin` guard, line 2912/2822), `guardKeys()`, and requires `SR`. Sets `aActive=true` and seeds `aData` (2916) — `{ lang, about:{interests}, goal, comfort, practice_time, intro, repeat_said, think_said, open_said, repeat_target:"My name is Sarah.", think_hindi:"Kal mujhe market jaana hai." }`.

Step chain (each renders into `#assessStep`, advances `#assessBar` via `aBar(pct)`):
1. **`aLangPick()`** (2923) — asked in Hindi; sets `aData.lang` = `hi`|`en`, then `aWelcome()`.
2. `aWelcome → aAboutName → aAboutWork → aDream → aInterests` — "About you" profile, written into `aData.about[field]` (`aChoiceAbout`, `aText`, 2969-3009).
3. `aGoal → aComfort → aPractice` (3020-3022) — `aChoice` writing to `aData.goal/comfort/practice_time`.
4. **`aStartVoice()`** (3025) — `POST /leveltest/gen {token, keys}` for **dynamic questions**; response overrides `aData.repeat_target` (`d.repeat`), `aData.think_hindi` (`d.think_hindi`), `aData._open` (`d.open`). On `402`→keys screen; `429`→`showNotif`; any failure silently falls back to built-in prompts. Then `aVoice(0)`.
5. **`aVoice(n)`** (3041) — iterates `A_VTASKS` (2827): `[{pct:52,field:"intro",kind:"open"}, {pct:66,field:"repeat_said",kind:"repeat"}, {pct:80,field:"think_said",kind:"think"}, {pct:92,field:"open_said",kind:"open"}]`. It renders the **same** sentence it speaks (`showLine` from `repeat_target`/`think_hindi`/`_open`, no hardcoded string). Speaking rules (3074-3077): `repeat`→say `v.intro` then `aData.repeat_target` in `ENG_SLOW()`; `think`→say `v.instr` then `aData.think_hindi` in `HI()`; `open_said`→say `aData._open || v.say`; `intro`→say `v.say`. Mic uses `listenOnce("en-US")` (learner always answers in English), writes transcript to `aData[t.field]`. `aSkip`/`aNext`→`goNext` → next task or `aEvaluate()`.
6. **`aEvaluate()`** (3081) — `POST /assessment {token, keys, ...aData}`; on failure shows retry / skip-all. On success → `aReveal()`.
7. **`aReveal(d)`** (3100) — sets `userState.onboarded=true`, `userState.profile`, `userState.progress`; **persists** `localStorage.dusu_state` and `dusu_onboarded="true"` (line 3105); renders `A_METRIC_LABELS` bars (confidence/pronunciation/listening/vocabulary/grammar/thinking), level badge, and speaks the profile message. `aDone`→`goHomeAfterAssess()` (3125) which sets `aActive=false`, `setWelcome()`, `renderHomeJourney()`, `refreshMe()`.

All copy is dual-language in `A_L.en` / `A_L.hi` (2835); `aL()` picks the object, `AL2(en,hi)` picks a string, `aVoiceProfile()` = `HI()` for hi else `ENG_NORM()`.

### 7.b Daily Talk (AI companion)

Entry: **`startDaily(from)`** (2648) with `from` ∈ `"speak"` (Start-Speaking hero / Daily nav tab), `"banner"` (Journey/"Continue" banner), or `""`. Guards `guardKeys()`, `SR`, `overLimit()`. State vars (2618): `drec, dLastEng, dLastNext, dailyTurns, dailyFrom, dailyInputs`. Opens WS and on `open` sends:
```js
{ type:"start", mode:"daily", token:authToken, mood:todayMood,
  hour:new Date().getHours(), resume:dailyTurns, keys:officeKeys() }
```
`dailyTurns = loadDailyResume()` (2625) restores recent turns from `localStorage.dusu_daily_resume` **only if ≤2 days old** (else removes it). `saveDailyResume()` (2621) stores `{date, turns:last-12, lastQuestion}`.

WS protocol handled in `onMessage` (2334): `daily_question`→**`greetDaily(m.question)`** (2714) — hides loader, pushes assistant turn, speaks question via `sayFace(question, HI())`, enables mic. `daily_turn`→**`handleDailyTurn(hindi, english, reply, tip, next_question)`** (2739): shows `#dailyCard`, sets tip (`setDailyTip`), then (1) says `HINDI.intro` + learner's line in `ENG_SLOW()` so they hear their sentence in English, (2) says DuSu's `reply` in `HI()` (never silent — falls back to `nextQ` then a canned line). Records both turns and `saveDailyResume()`. **Every 3 inputs** (only `dailyFrom==="speak"`, counted via `dailyInputs`) it speaks a Hindi reminder nudging the learning options and scrolls to `#dailyMore` (2760).

Listen loop: **`startDailyListen()`** (2723) — `SR` with `lang="hi-IN"`, sends `{type:"user_text", text}`; on no-speech says `HINDI.noSpeech`. `dcReplay` replays `dLastEng` in `ENG_SLOW()`; `dcNext`→`dailyContinue()` (2779) hides card and listens again. Orb animation via `dailyOrb(state)` (2639) driving `DAILYFACE`.

Options: **`renderDailyRecs()`** (2689) renders only **Talk** (`conversation`, 💬) and **Learn** (`learning`, 🎓) buttons — **"Day" was removed** (comment line 2694) as redundant on the daily page. `pickDailyRec(action)` (2706) → `leaveDaily()` then `chooseMode(action)`. Shown from the start only when `dailyFrom==="speak"` (2663).

Teardown: **`stopDaily()`** (2774) stops `drec` + cancels speech; **`leaveDaily()`** (2701) closes WS with `{type:"end"}`; **`finishDaily()`** (2785) — bound to both `#dailyFinish` and `#dailyBack` — ends WS, hides options, celebrates ("+20 XP · streak"), returns home.

### 7.c Conversation + Interview (session screen)

Entry: **`startSession(mode)`** (2265), `mode` ∈ `"conversation"|"interview"`. Interview first goes through `#setup` (`chooseMode` line 2087 → `show("setup")`; `#startInterview`→`startSession("interview")`). Guards `SR` and `overLimit()`. Sets titles (`#sessTitle`, `#sessSub`, `#endBtn` label/class differ per mode), `show("session")`, `orb("connecting", …)`.

`ws.onopen` (2282): `running=true`, `usageInc()+refreshUsage()`, then sends:
```js
{ type:"start", mode, name:$("name").value, role:$("role").value,
  token:authToken, mood:todayMood, seed:_convSeed, keys:officeKeys() }
```
`_convSeed` (Companion-Moment spoken answer) is one-shot, cleared after send (2286).

**`onMessage(ev)`** (2334) switch — cases used by session: `ai_text`→`addMsg(m.text,"ai")` + `speak(m.text)`; `interview_done`→`addSys`; `report`→`showReport(m.data)` (and completes a roadmap lesson if `currentLesson`); `ended`→`leave()`; `limit`→stop + orb idle; `quota`→`showNotif`; `keys_required`→force office mode + keys screen; `auth_error`→`logout()`; `error`→orb error. Client→server messages: `{type:"user_text", text}` and `{type:"end"}`.

**Voice loop** (`speak`↔`startListening`):
- **`speak(text)`** (2412): `stopListening()` (mic off — kills echo), `aiSpeaking=true`, orb "speaking", `FACE.startTalking()`, `u.onboundary` pulses the mouth. Has a 4s+`len*70`ms watchdog for Chrome's missing `onend` bug; on done → `delayedListen()` (waits `LISTEN_DELAY`).
- **`startListening()`** (2435): `SR` `lang="en-US"`; `onresult` (drops bleed if `aiSpeaking`) → `addMsg(text,"user")`, `pushThink()` (thinking-speed metric), sends `user_text`, orb "thinking". `onerror` `not-allowed`→stop; else `onend` retries with backoff (`safeRestart`, `srFails` capped at 8).
- Flags `running` (loop alive) + `aiSpeaking` (echo guard) gate the whole loop. `stopListening()` (2467) nulls `recog`.

`#endBtn` (2327) sends `{type:"end"}` and orb "Scoring…". `#backBtn`→`leave()` (2298).

**Report** `showReport(d)` (2488): animated count-up on `#ovVal`, SVG ring `#ringArc` fill, per-metric bars from `METRIC_LABELS` (grammar/fluency/confidence/communication/vocabulary/professionalism), filler-word chips, strengths/fixes lists, `better_answer` (Q + improved). `sparkle()` + `Assistant.happy()` if overall ≥80. **Share** (`#shareBtn`, 2314): builds a text summary, uses `navigator.share` or falls back to clipboard ("Copied ✓"). `#againBtn`→home + `speakWelcome()`.

### 7.d Learning (translate mode)

Entry: **`startLearning()`** (2555) — `chooseMode("learning")`. WS `start` payload `{type:"start", mode:"learning", token, keys}`. On `ready`→`greetLearn()` (2571) speaks `HINDI.greet`. `#micBtn`→`startHindiListen()` (2576): `SR` `lang="hi-IN"`, sends `{type:"user_text", text}`. Server replies `translation {hindi, text}`→**`handleTranslation(hindi, english)`** (2594): fills `#transCard` (`#tcHindi`/`#tcEng`), says `HINDI.intro` then the English in `ENG_SLOW()` **once** (no "repeat after me"). `#replayBtn` replays `lastEnglish`; `#continueBtn`→`startHindiListen()` again. `translate_error` case (2341) shows retry. `stopLearn()` (2603) nulls `lrec`.

### 7.e Practice section (hub)

`#practice` (1292) has three `.prac-block` (each = big centered `.prac-h` heading + one pill `.mode-card`):

| Heading (`.prac-h`) | `data-mode` | `<h3>` | Accent |
|---|---|---|---|
| **Convey your thoughts in English** | `learning` | Learn | `.learn` `#8f97e0` |
| **Face to Face English Talk** | `conversation` | Talk | `.talk` `#5fd0b0` |
| **Get Ready for Interview** | `interview` | Interview | `.interview` `#e6a99b` |

Styles (255-352): `.prac-block` is a centered flex column; `.prac-h` uses gradient-clipped ink + `drop-shadow` glow + an `::after` accent underline; `.mode-card` is a compact rounded pill (label + `.mc-orb` icon + `.mc-cta` arrow) — the verbose `p / .mc-chips / .mc-badge / .mc-wm` are `display:none` (336). Cards animate in with staggered `cardIn` delays and have a cursor-follow spotlight (`::before`, `--mx/--my` set in mousemove, 2096) + hover sheen (`::after`). Click handler `chooseMode(c.dataset.mode)` (2094).

`chooseMode(mode)` (2087): `guardKeys()` first; `interview`→`show("setup")`; `learning`→`startLearning()`; `daily`→`startDaily("banner")`; else `startSession("conversation")`.

### 7.f Voice teardown

**`stopAllVoice()`** (1875) is the single kill-switch for **both** loops: sets `running=aiSpeaking=false`, `stopListening()` (conversation `recog`), stops+nulls daily `drec`, `speechSynthesis.cancel()`, `FACE/Assistant.stopTalking()`, `dMicActive(false)`, and closes `ws` (nulling `ws.onclose` so the server persists state on disconnect). Called from `show()` when leaving any `VOICE_SCREENS`. **`visibilitychange`** listener (1910): when `document.hidden` and (`running` or on a voice screen) → `stopAllVoice()` — so switching browser tab / minimizing stops the AI.

### 7.g Home / Journey / Curriculum, Companion Moment, mood check-in

**Home hero**: `#startSpeak` "Start Speaking" → `startDaily("speak")` (2104). The living DuSu SVG face (`#hchar`, `HOMEFACE`) — eyes/lean follow the cursor (2120), smiles on Start hover (`homeHappy`), and tapping it plays a random `_DELIGHT` line (`dusuGiggle`, 2155). `goHome()` (2106) ends any WS, cancels speech, `closeMoment(false)`, `show("home")`. `setWelcome()` (3890) sets a time-of-day greeting + a day-rotated `HERO_LINES` headline and calls `renderToday/renderGrowth/renderTimeline/renderHomeExtras2`.

**`renderHomeJourney()`** (3256): gated on `onboarded` (cached `dusu_onboarded` flag, no `/me` wait); renders the "Where we left off" `#journeyBanner` (→`startDaily("banner")`), reveals `#roadmapLink`/`#leaderboardLink`, then `renderHomeExtras()` + `renderTimeline()`. **`renderHomeExtras2()`** (3907) paints `#homeChips` (streak/confidence/words from `userState.growth`) and the `#homeGoal` today card.

**Companion Moment** (`#moment`, 1171; still coded but hero now jumps straight to Daily): `openMoment()` (2177) adds `.moment-on` to `.hstage` (hides hero via CSS 396), fetches `POST /greeting {token,keys}` for a Hinglish line spoken on `GREET_VOICE()` (hi-IN), then `showRecs()` (2215) renders 3 `_recCard`s from `userState.recommendations` (primary/second/third, with fallback). `closeMoment(keepSpeech)` (2233) tears it down.

**Mood check-in**: `renderHomeExtras()` (3339) shows `#moodRow` once/day (`MOODS` = great/good/okay/low/tired, 3336) if no `checkins` entry for `todayStr()`. `doCheckin(mood)` (3386) sets `todayMood`, `POST /checkin {token,mood}`, speaks a per-mood line. Also renders `#eventBanner` (upcoming interview/exam) and `loadLetter()` (weekly "note from DuSu" via `POST /letter`, cached in `dusu_letter`). `todayMood` is fed into `daily`/`conversation` `start` payloads and biases lesson phrase choice (3656).

**Journey** (`openJourney()`→`renderJourney()`, 3434): stats chips (level/XP/streak/today from `jProg()`), focus tip from weakest `profile.weak_areas`, skills dashboard, roadmap. **Curriculum**: `CURRICULUM` array (3139) of 7 levels with `lessons[{id,en,hi,vocab,phrases}]`; `WORLD_NAMES`/`LEVEL_ICONS`/`BADGE_LABELS` (3128-3135). **Leaderboard** (`openLeaderboard()`, 3285): `GET /leaderboard` (Bearer auth) → `renderLeaderboard()` podium (top 3) + rows + pinned "you".

### 7.h Dashboard / admin (owner only)

**`openAdmin()`** (2004): `show("admin")`, `GET /admin/overview?token=…`. Renders owner name, counts (`total/active/pending/blocked`), a **"Require own keys"** switch `#reqKeysSw`, a **"Reset test users"** wipe button `#wipeBtn`, a **free-access email** manager (`#offEmail`/`#offAddBtn` + per-email Remove), and a per-user card list. Each user card shows role/status/mode/level/XP/streak/sessions/minutes/words + last-7-days activity, with action buttons: **Approve** (if not active), **Block/Unblock**, **Delete** (not for owner). Actions:
- `adminAction(id, action)` (1998) → `POST /admin/action {token, target_id, action}` (delete confirms first), then refresh.
- `#reqKeysSw` onchange (2050) → `POST /admin/settings {token, require_own_keys}`.
- `officeEmail(email, action)` (2061) → `POST /admin/office {token, email, action}` (add/remove).
- `#wipeBtn` (2054) → `POST /admin/wipe {token}` (deletes all except david, shuhani & free-access).

**Keys / BYOK** (`#keys`, `loadKeysUI()` 1947): Personal vs Office toggle (`useMode` in `localStorage.dusu_usemode`, `postMode()`→`POST /mode`). Key inputs Gemini/OpenRouter/GitHub/Groq. **`#verifyKeys`** (1971) → `POST /keys/verify {token, keys}`; needs **≥2 working keys** to pass — on success sets `localStorage.dusu_keys_ok="1"`, saves `dusu_office_keys`, and `routeAfterLogin()`. Gating helpers (1747-1773): `officeKeys()`, `officeAllowed()` (free_access/owner/unlimited), `keyCount()`, `keysVerified()`, `hasOwnKeys()` (≥2 & verified), `needsKeys()` (global switch on & not free), `mustAddKeys()`, and `guardKeys()` which redirects to the keys screen and returns `true` to block a session start.

### 7.i speak/say + SpeechRecognition + `speakable()`

- **`speakable(t)`** (2361): strips emoji/pictograph/arrow Unicode ranges so TTS doesn't read icon names, collapses `____` blanks and `----`/`====`/`**` markdown runs, and squeezes whitespace. Applied by every speak path.
- **`speak(text)`** (2412): the conversation-loop speaker (echo-guarded, watchdog'd, animates `FACE`/`Assistant`, auto-listens after).
- **`say(text, opts)`** (2538): a single **awaitable** utterance (returns a Promise) with its own watchdog and no pre-cancel — used everywhere sequencing matters (assessment, learning, daily). Voice profiles: `HI()` = `hi-IN`/rate 0.95, `ENG_SLOW()` = `en-IN`/rate 0.8, `ENG_NORM()` = `en-US`/rate 1.0 (3533-3535).
- Voice selection (2370-2410): `loadVoices()`/`pickVoice()` prefer **local (offline)** English voices (Edge "Natural" online voices often play silent), match `FEMALE_RE`/`MALE_RE`, and pick a natural `hindiVoice`. The header `.voicebar` `.vbtn` toggles `voiceGender` (persisted in `dusu_voice`; male button is `display:none`).
- Cartoon faces via `makeFace()` (1785): `FACE` (session `#eyes`), `HOMEFACE` (`#hEyes`), `DAILYFACE` (`#dEyes`) — procedural lip-sync (`startTalking/boundary/stopTalking`) + auto-blink. `Assistant` (1821) is the PNG-portrait path, disabled (`USE_PNG=false`) so the animated SVG is used.

### 7.j Auth, routing & localStorage keys

Boot: `authToken`=`dusu_token`, `authUser`=`dusu_user`, `userState`=null (3828-3830). `initAuth()` (4101): if `!AUTH_ENABLED` skip to home; else if token cached → `applyUser` + restore `dusu_state` + `routeAfterLogin()` + `refreshMe()`; else `show("login")`. Google callback `onGoogle(resp)` (4075) → `POST /auth/google {credential}` → stores token/user/onboarded; new user (`onboarded===false`) → `refreshMe()` (which routes to the guarded test), else `speakWelcome()` + `refreshMe()`. **`routeAfterLogin()`** (4045) is the one gate: keys (if `needsKeys() && !hasOwnKeys()`) → level test (if `onboarded===false`) → home. `refreshMe()` (4060) `GET /me` (Bearer; 401→`logout()`), caches full state to `dusu_state`. `logout()` (4034) clears all `dusu_*` keys and returns to login.

**localStorage keys used:** `dusu_token`, `dusu_user`, `dusu_state`, `dusu_onboarded`, `dusu_letter`, `dusu_daily_resume`, `dusu_keys_ok`, `dusu_usemode`, `dusu_office_keys`, `dusu_voice`, `dusu_usage`, `dusu_think`.

**Session limit:** `MAX_SESSIONS = Number("__MAX_SESSIONS__") || 20` (3857), tracked client-side in `dusu_usage` (`{d:date, n:count}`); `overLimit()`/`usageInc()`/`refreshUsage()` (3864-3877). `isUnlimited()` true for role owner/unlimited or `OWNER_EMAILS=["david123rana@gmail.com"]`.

**Backend endpoints the client calls:** WS `/ws/interview`; `POST /auth/google`, `GET /me`, `POST /mode`, `POST /keys/verify`, `POST /leveltest/gen`, `POST /assessment`, `POST /greeting`, `POST /letter`, `POST /checkin`, `GET /leaderboard`, `GET /admin/overview`, `POST /admin/action`, `POST /admin/settings`, `POST /admin/office`, `POST /admin/wipe`. **WS server→client message types** (`onMessage`, 2334): `ready`, `translation`, `daily_question`, `daily_turn`, `translate_error`, `ai_text`, `interview_done`, `report`, `ended`, `limit`, `quota`, `keys_required`, `auth_error`, `error`. **WS client→server:** `{type:"start", …}`, `{type:"user_text", text}`, `{type:"end"}`. PWA: `/manifest.webmanifest` + `/sw.js` registered on load (4128).

---

## 8. Mobile Apps, Cloudflare, Deploy & Dev/Ops

DuSu is a **single FastAPI service** (`backend/app/main.py`) that serves the frontend (`GET /` → `test_client.html`), the PWA manifest/service-worker, Google auth, and the `/ws/interview` WebSocket. Speech (STT/TTS) runs in the user's browser via the Web Speech API; the LLM is **OpenRouter** (called server-side). Everything below wraps that one service in a phone app, an edge front-door, and a $0 deploy.

### 8.1 Why a TWA, not a WebView (the whole reason `android-twa` exists)

DuSu's core feature is voice: mic speech-to-text + text-to-speech via the browser **Web Speech API**. A plain Android **WebView does not implement `SpeechRecognition`** — mic input silently breaks. The fix is a **Trusted Web Activity (TWA)**: it renders the live site full-screen *on the device's own Chrome engine*, so Web Speech STT/TTS behave exactly as in the browser.

Two Android modules exist; only the TWA is current:

| Module | Package | Status | What it does |
|---|---|---|---|
| `android-twa/` | `com.dusu.app` | **CURRENT** | Runs the site full-screen inside the app on Chrome's engine (TWA). Voice works. |
| `android-launcher/` | `com.dusu.launcher` | **DEPRECATED** | Old shim: a "Start DuSu" button that kicks the user out to *external* Chrome. minSdk 26. Has a `.github/workflows/build-apk.yml` cloud build. Kept only for side-by-side install (distinct package id). Do not develop further. |

Repo-root APKs: `DuSu-app.apk` (~3.1 MB, the TWA — this is the one you ship) and `DuSu.apk` (~5.9 MB, older). The build output is manually copied to `DuSu-app.apk` at repo root.

### 8.2 `android-twa` — the app

- **Loads:** `https://dusu-app-1.onrender.com/` (`strings.xml` → `launchUrl` / `hostName`).
- **IDs & SDK:** `applicationId = com.dusu.app`, `namespace = com.dusu.app`, `minSdk 21` (TWA runs on the device's Chrome, so old Android is fine), `compileSdk 34`, `targetSdk 34`, `versionCode 1` / `versionName "1.0"`, portrait-locked.
- **Toolchain (all version-locked, do NOT bump casually):**

| Thing | Version | Why pinned |
|---|---|---|
| `com.google.androidbrowserhelper:androidbrowserhelper` | **2.5.0** | 2.7.x pulls androidx.browser 1.10 / core 1.17 which demand **AGP 8.9.1 + compileSdk 36**. 2.5.0 (browser 1.4, core 1.7) builds clean on AGP 8.5.2 / SDK 34 and has every TWA feature used. |
| Android Gradle Plugin | 8.5.2 | matches SDK 34 setup |
| Kotlin | 1.9.24 | |
| `androidx.core:core-ktx` | 1.13.1 | `NotificationCompat` for reminders |
| Gradle wrapper | 9.3.0 | needs JDK 17+ |

**Launch path (critical, non-obvious):** `MainActivity` is the real `LAUNCHER` activity and it starts the TWA **directly** with `TwaLauncher(this).launch(url)` (see `MainActivity.kt` `launchDuSu()`). The manifest still *declares* `com.google.androidbrowserhelper.trusted.LauncherActivity` (with `DEFAULT_URL`, status/nav-bar color meta-data, `FALLBACK_STRATEGY=customtabs`, `autoVerify` intent-filter) — but that sub-activity is **not** used as the entry point; relying on it as the launcher no-ops for our flow. `MainActivity` is what runs.

**What `MainActivity.kt` does on start:**
1. Installs an uncaught-exception handler that writes the stack trace to `filesDir/last_crash.txt`. On next launch, if that file exists, it shows a **scrollable on-screen crash reporter** (white text on `#070A14`, selectable, "Clear & retry" button) instead of launching — lets you screenshot a crash with no USB/adb.
2. Shows a **splash** (`activity_main.xml` → `dusu_logo` + "Speak with Confidence" tagline) for ~1.2 s.
3. **Offline gate:** `isOnline()` checks `ConnectivityManager` for `NET_CAPABILITY_INTERNET`. Offline → 📡 "No Internet Connection" screen with a gold **Retry** button (`decide()` re-checks). Online → `launchDuSu()`.
4. `Notifications.createChannel()` + `scheduleEvery4Hours()` + requests `POST_NOTIFICATIONS` (Android 13+).
5. On return from the TWA (`onResume` with `launched=true`) it `finish()`es the shim.

**Reminders - SUPERSEDED 2026-10-20 (see section 18):** the static 4-hour `AlarmManager` reminder (`Notifications.kt`, `ReminderReceiver.kt`, `BootReceiver.kt`) was removed; notifications are now server-decided Web Push delivered through TWA notification delegation (`DelegationService`). The old text read: (`Notifications.kt`, `ReminderReceiver.kt`, `BootReceiver.kt`): local, no server. `AlarmManager.setInexactRepeating(RTC_WAKEUP, first=+4h, FOUR_HOURS_MS)`, channel id `dusu_reminders`, notif id `1001`. Message rotates by 4-hour slot from `strings.xml` `notif_messages` (`"title||body"` split on `||`, 6 messages). `BootReceiver` re-arms after `BOOT_COMPLETED` (alarms clear on reboot). Tapping opens `MainActivity`.

**Manifest permissions:** `INTERNET`, `ACCESS_NETWORK_STATE`, `POST_NOTIFICATIONS`, `RECEIVE_BOOT_COMPLETED`; a `<queries>` for `CustomTabsService` (Android 11+ package visibility, required to bind Chrome's Custom Tabs).

**Icon** (`gen_icons.py`, run via `backend/.venv/Scripts/python.exe android-twa/gen_icons.py`): slices `android-twa/icon-master.png` (the gold "D-mark" — a serif D whose counter is a woman's face + speech-bubble + sound-waves, per `DUSU_ICON_BRIEF.md`) into legacy mipmaps (48→192), adaptive **foreground** layers (108dp canvases 108→432), the splash `drawable/dusu_logo.png` (512), and `play-icon-512.png`. **Adaptive icon** = `mipmap-anydpi-v26/ic_launcher.xml` (+ `_round`): `<background>` = solid navy `@color/twaBackground` (`#070A14`), `<foreground>` = the mark. Theme (`themes.xml`) sets dark `windowBackground` + status/nav bar to `#070A14` to avoid a white flash.

### 8.3 Building the APK

```bash
cd android-twa
./gradlew assembleDebug     # → app-debug.apk — LOCAL adb testing ONLY (see warning below)
./gradlew assembleRelease   # needs keystore.properties → app-release.apk  ← this is what you share
./gradlew bundleRelease     # AAB for Play Store
adb install -r app/build/outputs/apk/debug/app-debug.apk
# repo-root DuSu-app.apk must be the RELEASE-signed APK (copy app-release.apk), never the debug one
```

> **Never share a debug-signed APK.** It is signed with Android's public debug key, which is not in `assetlinks.json`, so it ALWAYS shows the browser X + URL bar. Verify any APK with `keytool -printcert -jarfile <apk>`: its SHA-256 must be one of the fingerprints served at `/.well-known/assetlinks.json`. Play-installed builds are re-signed by Google — add the **Play App Signing** SHA-256 to `ANDROID_CERT_SHA256` too (comma-separated).

**BUILD GOTCHA — `JAVA_HOME` must be a real JDK 17.** Point `JAVA_HOME` at a standalone JDK 17 (e.g. `C:\Program Files\Microsoft\jdk-17...`), **not** the Android Studio bundled JBR. The bundled `jbr` causes Gradle/AGP toolchain failures here; the build config compiles against `VERSION_17` / `jvmTarget "17"` and Gradle 9.3.0 requires JDK 17+.

- `local.properties` → `sdk.dir=C:\Users\LENOVO\AppData\Local\Android\Sdk` (git-ignored, machine-specific — recreate on a new laptop).
- Release signing is **optional & lazy**: create `android-twa/keystore.properties` (git-ignored) with `storeFile`/`storePassword`/`keyAlias`/`keyPassword`. If absent, `assembleRelease` still runs but the APK is unsigned; use debug for testing. `gradle.properties`: `-Xmx2048m`, `useAndroidX=true`, `nonTransitiveRClass=true`.

**Full-screen (drop the Chrome address bar) needs Digital Asset Links — a two-sided handshake:**
- **App side** (already declared): `strings.xml` `asset_statements` trusts `https://dusu-app-1.onrender.com`.
- **Server side:** backend serves `GET /.well-known/assetlinks.json` (`main.py`) built from env `ANDROID_CERT_SHA256` (comma/newline-separated SHA-256 fingerprints, upper-cased) and `ANDROID_TWA_PACKAGE` (default `com.dusu.app`). Get the fingerprint via `keytool -list -v` on the debug or release keystore, set it on Render, then `curl -s https://dusu-app-1.onrender.com/.well-known/assetlinks.json` to verify. Reinstall the app; Chrome verifies both directions and runs edge-to-edge. Until verified it still opens — inside a Custom Tab bar (speech already works, the bar just isn't hidden). For Play App Signing, add **both** the upload-key and the Play-issued app-signing SHA-256.

### 8.4 Cloudflare failover (`cloudflare/` — PLANNED, not yet deployed)

Goal: one stable origin `https://dusu.ranabrothers.online` (a Cloudflare **Worker**) that serves DuSu from **your PC** when it's on and **Render** when it's off — same DB either way.

```
app / users → https://dusu.ranabrothers.online   (Worker: cloudflare/worker.js)
                 │ PC healthy? ──yes─► https://pc.ranabrothers.online → cloudflared → PC :8000
                 │              └─no─► https://dusu-app-1.onrender.com  (Render fallback)
                 ▼
              Neon Postgres   (single DB used by BOTH — no data split)
```

- `worker.js`: `pcHealthy(PC)` probes `PC_ORIGIN/health` with a 1.5 s timeout, result cached ~10 s in the edge cache (`caches.default`). Picks PC else CLOUD, forwards the original request **verbatim** (headers + body + WS `Upgrade`). Mid-flight failure retries CLOUD **only for plain HTTP** (a WebSocket can't be retried after upgrade); otherwise returns a 502 text. WS (`/ws/interview`) passes through.
- `wrangler.toml`: `name = dusu-failover`, route `dusu.ranabrothers.online/*` on zone `ranabrothers.online`; `[vars] PC_ORIGIN = https://pc.ranabrothers.online`, `CLOUD_ORIGIN = https://dusu-app-1.onrender.com`.
- **DB decision — SUPERSEDED.** That plan assumed a single shared managed database so PC/Render could never diverge. As of 2026-09-20 the database is the `db` container in this stack and there is no second origin to diverge from. If a Render/edge origin is ever revived it would need to reach this Postgres (or get its own) — the old "point both at the same managed URL" instruction no longer applies.
- Setup (all interactive, run by the human — see `cloudflare/README.md`): run backend on PC → `cloudflared` tunnel `dusu-pc` routed to `pc.ranabrothers.online` (installed as an always-on Windows service) → `wrangler deploy` + a **proxied** placeholder DNS record for `dusu` → only then repoint the app's `strings.xml` (`launchUrl`/`hostName`/`asset_statements`) to the Worker origin and add that origin to Google OAuth JS origins. Cost ≈ $0 (domain + free Cloudflare/Neon/Render tiers).
- **Status: none of the Cloudflare infra is deployed yet.** Only the app-side items (offline gate, 4h notifications) from that plan are built.

### 8.5 Deploy (Render — live, $0)

- **Repo:** `git@github.com:davidrana123/dusu-app.git`, branch **`main`**. **Render auto-deploys on every push to `main`.**
- **Live URL:** `https://dusu-app-1.onrender.com`.
- **Root dir:** `backend/`. **Build:** `pip install -r requirements.txt`. **Start:** from `backend/Procfile` → `web: uvicorn app.main:app --host 0.0.0.0 --port $PORT`. **Python:** `backend/runtime.txt` → `python-3.12.7`. No `render.yaml` (config is in the Render dashboard).
- `backend/requirements.txt`: fastapi 0.115.6, uvicorn[standard] 0.34.0, websockets 14.1, openai 1.59.6 (OpenRouter is OpenAI-compatible), pydantic 2.10.4, pydantic-settings 2.7.1, python-dotenv 1.0.1, google-auth 2.38.0, requests 2.32.3, sqlalchemy 2.0.36, asyncpg 0.30.0, greenlet 3.1.1.

**Required Render env vars:**

| Var | Purpose |
|---|---|
| `DATABASE_URL` | Postgres URL (asyncpg). Under compose it's injected from the `db` service. Absent → DB features no-op. |
| `OPENROUTER_API_KEY` + `OPENROUTER_BASE_URL` | LLM (OpenRouter, `https://openrouter.ai/api/v1`) |
| `LLM_MODELS` | comma-separated free-model fallback chain |
| `GOOGLE_CLIENT_ID` | Google Sign-In (login required when set) |
| `SESSION_SECRET` | signs DuSu session tokens |
| `ANDROID_CERT_SHA256` | APK signing fingerprint(s) → served in `/.well-known/assetlinks.json` |
| `ANDROID_TWA_PACKAGE` | optional, defaults to `com.dusu.app` |

`.env.example` documents these; real secrets go in `backend/.env` (git-ignored via `backend/.gitignore` → `.env`, `.venv/`, `users.db`, `__pycache__/`). Free tier caveat: the service **sleeps after ~15 min idle** (cold start ~30–50 s).

**Service worker / cache busting** (`backend/sw.js`, served at `/sw.js` with `Cache-Control: no-cache` + `Service-Worker-Allowed: /`; registered from `test_client.html` line ~4130): cache name is **`dusu-v5`** — **bump this constant** on any shell/asset change or clients keep the old cache. `activate` deletes all other caches. Navigations are **network-first** (so a new deploy shows immediately, falling back to cached `/` offline); static assets are cache-first-then-network. **Never cached** (live/per-user): paths starting `/ws`, `/auth`, `/me`, `/health`, `/lesson`, `/level`, `/assessment`, `/admin`, `/keys`, `/mode`, `/.well-known` (and all non-GET). PWA install comes from `manifest.webmanifest` (standalone, portrait, `#070a14`, icons from `/logo.png`).

### 8.6 Local dev

```powershell
# backend (from repo root)
cd "C:\Personal Work\English Specking\backend"
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# → open http://127.0.0.1:8000/  (health: /health → {"ok":true,"has_key":..,"providers":[..]})
```

Secrets in `backend/.env` (never committed); DB credentials live in the root `.env` (`POSTGRES_*`) and compose builds `DATABASE_URL` from them. `docker compose up -d` is the **production** run (code baked into the image). The dev loop is `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d`, which mounts `./backend` and runs uvicorn with `--reload` so edits apply without a rebuild. The dev overlay is deliberately not named `docker-compose.override.yml`, so a bare `up` can never turn the live deployment into a dev container.

### 8.7 Verification workflow & hard-won lessons

- **`import app.main` before every deploy.** Run the module import (e.g. `python -c "import app.main"` in the backend venv) to catch **runtime import / `NameError`s that `ast.parse` (syntax check) does NOT catch**. A `TokenIn` `NameError` once crashed the deploy on boot because it passed a syntax check but blew up at import time — always do the real import.
- **Frontend inline JS:** validate `test_client.html`'s inline `<script>` with **`node --check`** / a `vm.Script` compile, not by eye — a single syntax error white-screens the whole app.
- **Poll live after deploy:** `curl` the live URL (or `/health`) for a known marker string to confirm the new build actually went out before declaring success (Render auto-deploy + cold start means "pushed" ≠ "live yet").
- **LF/CRLF git warnings are harmless** on this Windows repo — ignore them.

### 8.8 Known issues / Pending / Deferred

- **App crash diagnosis** relies on the on-screen crash reporter (`last_crash.txt`); root-cause of any TWA launch crash still to be confirmed on a real device.
- **Cloudflare local-first infra is NOT deployed** — Worker, `cloudflared` tunnel, `pc.ranabrothers.online` DNS, and repointing the app to `dusu.ranabrothers.online` are all pending. App still points at Render directly.
- **Full lock screen for blocked/quota-exhausted users** not implemented app-side.
- **DB-encrypted key storage (BYOK)** — user-supplied LLM keys are not yet encrypted at rest (see `DUSU_BYOK_PLAN.md`).
- **Play Store** listing not published (AAB build path exists; needs both upload + Play App Signing SHA-256 in `ANDROID_CERT_SHA256`).
- **`android-launcher` is deprecated** and should be removed once the TWA is fully validated.
- Free-tier **Render cold starts** (~30–50 s) remain; no keep-alive pinger configured.

---

## 9. Practice Room (flag-gated, built 2026-10-06 — design in `DUSU_PRACTICE_ROOM_PLAN.md`)

Rehearse a presentation → record on the phone → transcribe → scored report → listen back → retry. Hindi, Hinglish or English (plan §13). **Dark by default:** `settings.practice_room` = `off` (default) / `owner` / `on`, flipped from the owner dashboard (More → Dashboard → Access → Practice Room); the client reads it as `/me.practice_room` and draws no entry point while it is off.

| Piece | Where |
|---|---|
| Scoring | `backend/app/practice.py` — measured metrics from word timestamps (pace, pauses, restarts, pace variance, time, recogniser confidence) + LLM judgements; English weights 20/15/5/10/20/10/10/10, Hindi/Hinglish 25/30/15/15/15 (no Grammar/Vocabulary/Clarity — plan §13.6); median of `RUNS`; quote verification; `compute_delta` (changes under 5 points are noise); `invite_decision` (the English-invitation nag guard); `build_bridge` |
| Prompts | `interview/prompts.py` → `practice_analysis_system()`, `practice_bridge_system()` |
| Endpoints (`main.py`) | `POST /practice/analyze` · `/practice/bridge` · `/practice/prefs` · `/practice/delete` · `/practice/transcribe` (server proxy, only for accounts on DuSu's own keys) · `GET /practice/history` · `/practice/attempt?id=` |
| Data (`db.py`) | table `practice_attempts` (scores + report only — **recordings and transcripts never reach the server**); `session_scores.vocabulary/grammar_trend` are NULLable ("not scored" ≠ 0, migration in `init_db`); prefs in `memory.facts.practice_prefs`; `award_speaker_progress(..., unscored=)`; new modes in `_MODE_BONUS` (an unknown mode is silently logged as "conversation") |
| Client (`test_client.html`) | the `PR` module near the end of the script + `#pr*` sections / `.pr-*` CSS. Recording = `MediaRecorder` → 10 s chunks mirrored to IndexedDB `dusu-practice` (crash recovery) → Groq Whisper **straight from the phone with the student's own key** (`savedKeys().groq`); takes are tagged with the account and wiped on account deletion |

**Gotchas:** `llm.assess(..., temperature=)` — scoring runs at 0.2 (the default 0.7 re-scores the same speech up to 15 points apart). `_extract_json` now repairs the two broken-brace shapes Gemini-lite emits (~1 reply in 9), so gate fields (`genuine_effort`) are also computed server-side. Never log a transcript (`_safe_err`). Because the server's Groq key is dead, accounts on DuSu's keys cannot transcribe until it is replaced — BYOK users with their own Groq key are unaffected. Not yet verified on a physical phone/TWA: recording permission, Wake Lock, battery, Whisper on Hindi/Hinglish (plan §7 spikes S1/S2b/S3b).

---

## 10. DuSu knows your data (Life Context — built 2026-10-10)

DuSu's memory block (`main._facts_summary`) holds who the learner IS; it held none of their NUMBERS, so "what's my streak?" got an invented answer. `backend/app/life.py` reads what Postgres already has and renders ONE short block that `main.py` appends to `facts_summary` at WS `start` for **conversation + daily** (not interview — a role-play; not learning — a translator). The block is the lines below plus a fixed "how to use" rule: answer from exactly these numbers, say so when something isn't listed, never guess or round up, don't recite stats unprompted, never scold with a number.

| Piece | Where |
|---|---|
| Read | `db.life_snapshot(uid)` (profile + progress incl. `last_active` + the memory doc + SessionScore counts per mode, ONE session) · `db.weekly_league(uid, limit=1)` (own rank only) · `db.speaking_trend` · `db.list_practice_attempts(uid, 3)` |
| Render | `life.render(...)` — pure (no I/O), priority-trimmed to ~1,700 chars. Essentials that never go: level check, streak, today, Speaker rank / XP, roadmap. Dropped first: tenure, badges, missions, confidence check, career, trend |
| Wire | WS `start`: `life.build(uid)` runs as a task alongside the memory reads, `wait_for(…, 3 s)`; any failure or timeout → the chat opens without numbers |
| Switch | `settings.life_context` = `off` / **`owner` (default)** / `on`, via `life_context_enabled(email)`; dashboard → Access → "DuSu knows your progress" (`/admin/overview.life_context`, `/admin/settings`). It changes what DuSu says in every Talk, so it is staged like the Practice Room |
| Extension | `life.EXTRA_LINES` — a module appends `async fn(uid) -> list[str]` (1.5 s each, failures dropped). The Goals planner plugs in here (`DUSU_GOALS_PLAN.md` §10) |

**Gotchas:** `Progress.streak_days` and `sessions_today` are only reset by the NEXT activity, so a lapsed streak keeps its old number — `render` counts the streak as alive only if `last_active` is today or yesterday (IST) and treats `sessions_today` as 0 otherwise. The block is built once per conversation: a lesson finished mid-chat shows up in the next one. Free text (practice topic, role, goal) is flattened to one quote-safe line (`_clean`) because it lands inside a system prompt. Only the caller's own data goes in — the league line is their own rank, never another learner's alias. **Verified 2026-10-10** on a scratch database with the real model: numbers exact in Talk and Daily Talk, an honest "I don't have that" for data that isn't listed, no stats recited in the opening greeting, a second learner's sentinel data never leaks, slow/failing reads never block the chat. **Not covered:** Hindi wording quality beyond one sample, and any provider other than Gemini (the only one alive on the server today).

---

## 11. Hindi ⇄ English choice — the NEW features only (built 2026-10-10, re-scoped 2026-10-11 — `DUSU_LANGUAGE_SCOPE_PLAN.md`; the original all-modes design is `DUSU_BILINGUAL_PLAN.md`)

**The rule.** One global language — `hi` (the **default**) or `en`, switchable any time — and it belongs to the **new features only**: the Home AI companion (chat + **Know About DuSu**) and, when built, My Day. The **old features never change with it**: Daily Talk (the original Hindi chat — learner speaks Hindi, DuSu answers in Hindi, English line + tip card), Face-to-Face (English), Interview (English, English report), Learn ("convert Hindi to English", Hindi → English only, no direction switch), Journey, Ranks, Practice, Profile, Keys, the bottom nav and every static screen. Not by the dashboard switch, not by the saved preference, not by a `lang` the client sends or a `lang`/`dir` tag on a server frame. The **database is shared**: the new features' AI sees everything the old ones saved (memory, summaries, numbers — and Home also gets Daily Talk's today/yesterday notes), and the choice itself lives in the DB (`memory.facts.lang_pref`, no migration) so it follows the learner across devices.

**The switch.** `settings.bilingual` = off / **owner (default)** / on (dashboard → Access → "Hindi / English switch (new features)"). It is now a switch *for the new features*: off = they are Hinglish only and no control is drawn. The control is drawn only where a new feature is live: **Home page**, **Home chat header**, **Know About** — and only when `userState.bilingual && HM.enabled()` (switch on but Home AI off ⇒ nothing, the old Home hero is untouched).

| Piece | Where |
|---|---|
| **The registry** — the ONE place that decides which modes obey the choice | `backend/app/lang.py`: `SWITCHABLE = ("home",)`, `session_lang(mode, requested, switch_on)` (→ the learner's choice only for a switchable mode with the switch on, else `LEGACY[mode]` = what the mode always was); client mirror `LG` `SWITCHABLE = {home:true}`. **A new feature joins by adding its mode here (both sides) and drawing its own switch** |
| Server | WS `start`: `bilingual_on = (mode in SWITCHABLE) and await bilingual_enabled(email)`; `Session(lang=session_lang(...), bilingual=bilingual_on)`. For an old mode `bilingual_on` is False, so the session is built exactly as before any language mode existed, and a `{"type":"lang"}` frame is ignored (no `lang_ok`). `/me` adds `bilingual`, `lang`; `POST /lang` saves the choice (`learn` still accepted, ignored) |
| Client | `LG` (one block after `killSpeech`): `lang(mode)` is pinned to `LEGACY` for old modes; `tr()`/`lgt()` returns the **original English everywhere except inside the Home chat**; **no static re-writing** (`LG_STATIC` removed), **`<html lang>` is never changed**, no Learn-direction control; server frame tags are ignored for old modes (`speak`, `greetDaily`, `handleDailyTurn`, `handleTranslation`); `pills()` shows each switch only in its context (`data-lg-sw=""` Home + Know About, `"chat"` only while the Home chat is open); a language change on Know About re-fetches the page (`LG.set` → `HM.openAbout`) |
| **Parked** (kept, unreachable) | The Hindi/English branches for Talk / Interview / Daily / Learn in `engine.py` / `prompts.py`, `lang.LINES/SEED`, `I18N.hi` strings for old screens, `LEARN_SAY`, `dusu_learn_dir`. To bring a mode back: add it to `SWITCHABLE` (server + client) and draw its switch |

**Removed on purpose:** the *voice polish* (`Session(polish=)` — Daily Talk / Face-to-Face softening "सुप्रभात" → "Good morning" for Home-AI learners). It changed old-feature output, which this rule forbids. `home_content.soften()` stays for the Home companion only. The need was real (the live Daily Talk sometimes opens with "सुप्रभात"); if the owner wants it, build it as its own opt-in switch, not tied to Home.

**Gotchas:** the helper is **`lgt()`, not `t()`** — the script has many local `t` variables. `LG` is a top-level `const`, so it is NOT `window.LG` (a harness must use `typeof LG`). `LG.on()` alone is not "draw the switch" — it needs `HM.enabled()` too. Hindi copy for the new features = Devanagari with everyday English words in Latin (~75% Hindi words; romanised Hindi is mispronounced by the voice); DuSu speaks as a woman and the prompt forbids guessing the learner's gender; तुम, never तू; the English recogniser stays `en-US`. Practice Room keeps its own language choice (new feature, unaffected).

**Verified (2026-10-11) — "old = old" is proven by DIFF, not argued.** *Server:* 180 scenarios (6 mode values × 6 `lang` values × 5 mid-session `lang`-frame sequences) through the real `/ws/interview` handler with a stubbed model — the pre-language tree (`6db1979`) vs the new tree, switch OFF **and ON** — 1,350 frames and 630 model calls **identical**; every `lang`/`dir` tag the new server puts on an old-mode frame is the legacy one (1,140 checked). The same harness on the previous commit leaks (14/180 identical, 854 non-legacy tags), so it does discriminate. *Client:* 89 observations (whole text of every old screen, nav, `<html lang>`, voice, recogniser locale, wire frames for Talk / Interview / Daily / Learn) identical to the pre-language client in 7 variants (switch off / on, saved `hi` / `en`, device cache `dusu_lang=en`, **hostile server tags** `lang:"en"` on Daily and `dir:"en2hi"` on Learn, runtime flips through the real pill); the previous commit's client leaks 29 of them. 55 boundary checks (the switch exists only on Home / Home chat / Know About; flipping it re-writes Home and changes **not one** old screen; switch on + Home AI off draws nothing). *Real stack:* 112 scratch-DB checks with the real model (switch ON for everyone: Face-to-Face and Interview open in **English** although Hindi was asked, Daily Talk stays Hindi, Learn stays Hindi → English with `dir:"hi2en"`, a mid-session `lang` frame is ignored, Home still obeys the choice) and **41 real end-to-end checks** (real Chromium → real HTTP + WebSocket → the new code in a throwaway container → scratch DB → the real model chain), including the decisive one: **English saved + switch on ⇒ Daily Talk still opens in Hindi with the original card, Face-to-Face opens in English, Learn translates Hindi → English.** **Not verified:** a real phone — Hindi voice availability/quality on Android, recogniser accuracy on Hinglish, Devanagari font rendering on the owner's handset.

---

## 12. Home 2.0 — AI companion first (built 2026-10-10 — design + status in `DUSU_HOME_AI_PLAN.md`)

Home becomes one thing: DuSu. A time-aware **Hinglish** greeting ("Good morning Asha! आज का दिन कैसा शुरू हुआ?" — never सुप्रभात / शुभ संध्या), four things to say, **Start Speaking** (DuSu speaks first, aloud, then listens), a **Know About DuSu** page and a type box. Start Speaking opens the **main AI conversation** (WS mode `home`, drawn on the existing `#session` screen); **Daily Talk stays its own tab and route, unchanged**. Behind `settings.home_ai` = off / **owner (default)** / on (dashboard → Access → "Home AI companion"). **Switch OFF = today's Home exactly** — proven by diffing the old HEAD against the new code: server prompts + model inputs byte-identical for every pre-existing mode; client 17 Home observations (visible text, element order, Start Speaking → Daily Talk with the same wire frame / URL / nav tab) and the 55 Hindi/English-layer observations identical.

| Piece | Where |
|---|---|
| **Registry** — ONE source for the Know About page, the model's catalogue AND the validation of the ids it suggests (they cannot disagree) | `backend/app/home_content.py`: `FEATURES` (hi/en copy, `live`/`soon`, `needs` switch, `route`), `INTENTS`, `page()`, `actions()`, `catalog()`, `detect_intent()` (keyword fallback, Devanagari + Latin), `fallback_reply()`, `soften()` (stiff Hindi → "Good morning", "please"…) |
| Prompt | `interview/prompts.py`: `home_system(...)`, `_HOME_VOICE_HI/_EN`, `_HOME_RULES` (the honesty rules) |
| Session | `engine.Session(mode="home", home_flags=, home_personal=, new_learner=, hour=)`; `home_turn(answer)` = ONE model call → `{reply, intent, suggest}`, one retry on broken JSON then a true deterministic fallback, ids validated, `summarize_and_extract` adds a Home note |
| Wire | WS `start {mode:"home", opening, lang, hour}` → `home_ready` — **no model call**: the client already spoke the greeting it was showing; `opening` is sanitised (`_clean_opening`) and becomes the first assistant line · `user_text` → `status thinking` → `home_turn {text, lang, intent, actions[{id,label,route}]}` · failures: `home_error` / `quota` / `limit` (cap = `conversation_max_turns`) |
| HTTP | `GET /home/features?lang=` (the page for THIS learner; 404 while the switch is off) · `POST /home/prefs {personal}` (privacy, `memory.facts.home_prefs`, no migration) · `/me` adds `home_ai`, `home_personal` |
| **Feature icons** (2026-10-11) — one tap into any feature from Home | `home_content.tiles(flags)` → **`/me.home_tiles`** (`[{id, icon, route, t:{hi,en}}]`, sent **only when `home_ai` is on**, so everyone else's `/me` is unchanged): the built features for THIS learner in registry order (Practice Room only when switched on; never a "coming soon" feature, never Know About). Client `HM.renderFeats()` fills `#hmFeats` (CSS `order` 8: under the type box, above the older cards) with icon tiles — an inline **SVG line icon** per id (`HM` `ICONS`; the registry emoji is the fallback), a 2-line label, the heading follows the Hindi/English choice, both titles ride in the data so switching needs no fetch. A tap is `navTo(route)` — exactly "Try it" on Know About (same guards, Back button, URL); a tile whose route the client lacks is **skipped**; no tiles / Home AI off ⇒ hidden |
| Persistence | remembered (summary → `conversations` row mode `home`, facts, next hook, `recent_turns` tail tagged `home`) but **never scored or rewarded** — no XP, streak, league, vocabulary, minutes or badges; its questions aren't added to `recent_questions` |
| Client | `HM` module (before `initAuth()`); Home markup `#hmLabel/#hmChips/#hmAbout/#hmType`, chat controls `#hmLive` (inside `#session`), screen `#about`; CSS `hm-*` / `ab-*` (inert unless `#home.hm-on`); routes `/home-chat`, `/about`; `LG` LEGACY gets `home:"hi"` and `tr()` uses the Hindi table inside the Home chat **even with the Hindi/English switch off** (the language layer is scoped to the new features — §11); small hooks in `show()`, `syncNav`, `pathForScreen`, `startListening` (mic denied → text mode), `onMessage` (3 cases), `setWelcome`, `speakWelcome` (silent when Home 2.0 is on), `dusuGiggle` |

**How it behaves.** The greeting is chosen **in the browser** (instant, no network, never any private data — first name + time of day only): 4 time segments (5–11 / 12–16 / 17–20 / 21–4) × 3 variants + a new-learner set + an English set, never the previous variant (`localStorage dusu_hm_last`), stable for 20 min. **Start Speaking** speaks it at once, opens the socket in parallel, and the mic opens only after the greeting AND `home_ready` (exactly once). A **chip** or **typed text** skips the spoken greeting and sends that as the first message. **DuSu only suggests**: the model's `suggest` ids are checked against `home_content.valid_ids(flags)` (unknown / "coming soon" / switched-off ids dropped, ≤ 3) and drawn as buttons; navigation happens only on a tap — leaving `#session` closes the socket, which saves the chat. **Text mode**: typing = no voice in or out; mic denied / no `SpeechRecognition` (Firefox) = text mode with a visible notice; the 🎤 button switches back; tapping the orb interrupts DuSu. The input row is `position:sticky` above the 76 px bottom nav on phones, so after every turn the page scrolls to the newest line (`toLatest()` — otherwise the bar covers it); the orb shrinks on phones (140 px on short screens).

**Shared database (2026-10-11).** The Home companion's memory block is everything the learner told every feature: memory facts, the exact numbers (`life.build`) and — new — what they told **Daily Talk** today / yesterday (`main._home_daily_block`: mood, plans, weather, events), labelled "WHAT THEY RECENTLY TOLD DAILY TALK" and presented as **their own words, never a task list** ("you mentioned an interview", never "I saved it"; one rule bullet in `_HOME_RULES`). The privacy switch removes it with the rest.

**Voice polish — REMOVED 2026-10-11** (see §11). It softened "सुप्रभात" → "Good morning" in Daily Talk / Face-to-Face for Home-AI learners (`Session(polish=)`); that changed old-feature output, which the language-scope rule forbids. `soften()` now serves the Home companion only.

**Honesty rules (the product's trust).** The planner is a plan, not built — so the prompt says there are **no saved tasks**, never "I saved / will remind you", numbers only from `life.build` (owner switch `life_context` must also be on for the numbers), memory only if listed and never with added details ("yesterday"), features only from the catalogue by NAME (never an id), no romance. Know About shows **Goals & Daily Planning as "Coming soon" with no link**. **When the Goals planner ships:** flip its `home_content` status to `live` + give it a `route`, plug its numbers into `life.EXTRA_LINES`, delete the "do NOT exist" rule in `_HOME_RULES`. Privacy switch (Know About page, default ON): off → no memory, no numbers, name from the sign-in only, and the prompt says so.

**Android "browser X + URL bar" (TWA).** Measured cause: the shipped release APK is linked (`assetlinks.json` lists the upload key; Google's checker says `linked:true` on both hosts), but a **Play-installed** copy is re-signed by Google and that key isn't listed. New: `assetlinks.json` = env `ANDROID_CERT_SHA256` + up to 3 fingerprints the owner adds at runtime (Settings `android_cert_extra`); dashboard → **Android app link** (list / add / remove / **Check with Google**); endpoints `GET/POST /admin/applink`, `POST /admin/applink/check` (owner only). The owner must paste Play Console → Setup → App signing → "App signing key certificate" SHA-256 — nobody else can read it. Steps in `DUSU_HOME_AI_PLAN.md` §9.

**Gotchas:** `re` `\b` doesn't work on Devanagari and the danda `।` (U+0964) lies inside the Devanagari block — `soften()` builds its boundary class without it. Chromium has native `SpeechRecognition` AND `webkitSpeechRecognition`: a "no recogniser" test must remove both. Don't put backslashes in Bash-tool heredocs that generate Python (they are halved) — write patch scripts with the Write tool. Greeting/Know-About Hindi avoids gendered forms toward the learner (no रहे हो / सकते हो / बोलोगे…); DuSu is feminine about herself.

**Verified (2026-10-10):** 127 pure-logic checks (registry, intents, `soften`, action validation, prompt contents, `Session.home_turn` with a stubbed model incl. retry / fallback / switch note / privacy, voice polish [removed 2026-10-11], route cross-check against the client) · 117 Chromium checks with a fake socket / recogniser / voice (every time segment × variant × both languages: Hinglish, time-correct, first name only, no stiff or gendered words, no private data; Start Speaking speaks first and opens the mic once; chips; actions open the real routes; text mode; mic denied; no recogniser; error / quota / dropped connection; interrupt; End; Know About incl. the Coming-soon card and the privacy POST; English; phone + desktop screenshots) · **35 REAL end-to-end checks**: a real Chromium page → real HTTP + WebSocket → the new code in a throwaway container (scratch DB + scratch session secret, loopback port + SSH forward) → the real model chain (honest "no saved tasks", the real streak from the DB and no invented numbers, privacy switch, Daily Talk still opens after a Home chat, **no XP / streak change**, thread saved, English) · 93 scratch-DB server checks with the real model (switch, `/me`, `/home/*`, admin, app-link endpoints, wiring, privacy, persistence, honesty/boundary/numbers, Hinglish style) · **flag-off parity**: old HEAD vs new — engine + every pre-existing prompt (EN + HI) + lang tables byte-identical, client 17 Home + 55 Hindi/English observations identical · regression suites re-run on the new code: Hindi/English modes all pass except one stochastic real-model threshold (Hindi interview follow-up Devanagari ratio; prompts byte-identical), DuSu-knows-your-data passes except `speaking trend (same-day fallback)`, which **fails identically on the old HEAD** (pre-existing, not from this change). **Not verified:** a real phone (Hindi TTS voice availability, `hi-IN` recogniser accuracy on Hinglish, the sticky input row with the on-screen keyboard), a Play-installed build losing its browser bar (needs the fingerprint above).

**Update 2026-10-11 (feature icons, shared database, language scope) — verified:** 138 pure-logic checks (`tiles()`, `/me.home_tiles` only with `home_ai`, `_home_daily_block`, the scope registry) · 28 Chromium checks on the icon grid (8 / 9 tiles in registry order, real SVG icons, ≥ 44 px targets, 4 per row, odd tile centred, **every tile opens its route and the URL follows**, the heading follows the language with no fetch, a tile with an unknown route is skipped, hidden when Home AI is off or there are no tiles, 320 px phone + desktop) + screenshots · the 117 Home 2.0 checks still pass · the 112 scratch-DB and 41 real-browser checks of §11 (the real `/me` carried the tiles; the real model referred to the interview the learner told Daily Talk as *their own words* and never claimed to have saved it). **Not verified:** the icon grid on a real handset (looked at in Chromium at 390 / 320 / 1280 px).

---

## 13. Practice Room - all six kinds, and a Home that answers (built 2026-10-11 - plan + status in `DUSU_ALL_FEATURES_PLAN.md`)

Owner's words: "where is viva, practice option? ... in Home -> Start Speaking nowhere need to go ... we can ask: what is the time, routine, my progress". Two findings: the Practice Room was **off for everyone** (prod `settings` held only `level_test`) and only *Presentation* existed; and the Home chat had **no clock** and sent people to other screens. Both fixed; the Practice Room switch is now `owner` in prod (set 2026-10-11; "Everyone" is the owner's call - it records audio, so the Play Data-safety form must match first).

| Piece | Where |
|---|---|
| **Conversation kinds** (viva / discussion / custom role-play) | `backend/app/practice_talk.py` - `talk_system()` (examiner / moderator + "Arjun" / the other person in the learner's scenario), `scorer_system()` + `analyze_talk()` (median of 2 runs at temperature 0.2, same report shape as a presentation), `SKILLS` / `WEIGHTS` per kind, `scenario_blocked()` |
| Wire | WS `start {mode:"practice", kind, topic, plang, level, rounds, feedback_lang}` -> `ai_text` ... `practice_done` -> `practice_report {data}` / `practice_error {msg}`. `end` scores what was said (>= 2 answers and 15 words, else a friendly `too_short`, nothing saved). A failed scoring resets `practice_done`, so **End** can be tapped again on the same conversation. `Session.next_ai_turn` AND the (currently off) streaming path end on the marker or at `rounds` |
| Gates (`main.py` WS `start`) | `practice_room_enabled`, kind in `TALK_KINDS`, topic >= 3 chars (angle brackets stripped), daily attempt cap (30), a `custom` scenario that is romantic / sexual is **refused before any model runs** |
| Saved as | an ordinary Practice attempt (`_practice_talk_save`: `practice_attempts` row with scores + report only - **no transcript**, a one-line summary for DuSu's memory, Speaker XP via `award_speaker_progress`, weekly missions, vocabulary, badges). Hindi / Hinglish: vocabulary + grammar stored as NULL, `language` category absent |
| Recording kinds (presentation / speech / seminar) | unchanged pipeline; `/practice/analyze` answers 400 for the conversation kinds |
| Transcription | `/practice/transcribe`: Groq Whisper when a Groq key exists, else (or on 401 / 403 / 429 / 5xx) **Gemini** `generateContent` with the audio inline (`_gemini_transcribe`; flash-lite for English, flash for Hindi / Hinglish; returns Groq-shaped JSON with `words:[]`, `segments:[]`, `engine:"gemini"` - the scorer then says "model's read only" for pace / pauses). **The server's Groq key is dead (403)** - this is why accounts on DuSu's own keys can transcribe at all |
| Badges | `first_viva`, `viva_80`, `first_discussion`, `first_speech`, `first_seminar`, `first_custom` (`db.check_practice_badges`, `BADGE_LABELS`) |
| Home answers in place | WS `start` carries `tzmin` (the device's UTC offset); `home_content.now_text()` -> `RIGHT NOW (the learner's own clock ...)` in the prompt every turn; `INFORMATIONAL` intents (`time_date`, `goal_progress`, `daily_plan`) and plain chat get **no buttons** (`filter_suggest`); a request to DO something still gets its button. Home reads the learner's numbers (`life.build`) whatever the Talk `life_context` switch says - its own privacy toggle governs. Time questions have a deterministic fallback (`time_line`). Chips: Time / Routine / Progress / English practice |

**Gotchas / measured:** with only a prompt rule, the real model **played** "act as my romantic girlfriend" - the keyword filter (`_BLOCKED_SCENARIO`) is the layer that does not depend on the model; the prompt keeps a STEP ZERO check as the second layer (medical advice and impersonating a real person are declined by the prompt alone - verified). The examiner repeats a question once when the answer does not address it (intended). A model that is only told "list MUST be empty" still labelled small talk `english_practice` and suggested Daily Talk - the INTENT line now defines `general_conversation` explicitly. The Hindi reply once transliterated the nickname "Chhoti" into "छवी": the prompt now says to write the name exactly as given, in Latin letters. Do not log exception text from `_practice_talk_save` (SQLAlchemy messages carry the parameters): class names only.

**Verified (2026-10-11):** `home_unit.py` 173 + `talk_unit.py` 105 pure checks; scratch-DB stub selftests (Home 95, practice WS 53 incl. the REAL Gemini transcription of a spoken clip); **real model**: strong viva 76-85 vs weak 24-27, Hinglish discussion 79-81, medical / impersonation role-plays declined, Home `time` / `day` / `progress` answered from the device clock and the real DB numbers (also UTC-5), plain chat without buttons; browser suites (Home look 123, scope boundary 55, tiles 28, Practice Room 87 + 39); **old-feature parity**: server A/B 180/180 scenarios identical (HEAD vs working tree, switch on and off), client A/B 89/89 identical in 7 variants. **Not verified:** a real phone (recording permission, Wake Lock, Hindi / Hinglish transcription quality through Gemini, the conversation kinds' voice loop on Android).

---

## 14. My Day - tasks, habits, goals, reminders (built 2026-10-11 - design in `DUSU_GOALS_PLAN.md`, scope in `DUSU_ALL_FEATURES_PLAN.md` W3)

The thing Know About DuSu listed as "coming soon". **Ships dark:** switch `settings.planner` = `off` (code default) / `owner` / `on` (owner dashboard -> Access -> "My Day"; `/me.planner`; the planner endpoints answer 404 and the scheduler idles while it is off for an account). One package, all new `pl_*` tables (no existing table altered):

| Piece | Where |
|---|---|
| Pure logic | `backend/app/planner/timeutil.py` (per-user IANA zone, DST-safe wall clock -> UTC, recurrence daily / weekly / monthly with `interval`, `until`, `count`, quiet hours) and `rules.py` (cleaning, limits, task state, goal progress, habit consistency / streak) - no DB, no clock except an argument |
| Tables | `planner/models.py`: `pl_prefs, pl_goals, pl_milestones, pl_tasks, pl_habits, pl_habit_logs, pl_reminders, pl_push_subs, pl_events`. Partial unique indexes: `(user_id, client_key)`, `(parent_id, occ_date)`, `occurrence_key`. **Check column widths against every value the code writes** (`push_state` was `String(14)` and `"no_subscription"` has 15 characters - caught only by the scratch-DB run) |
| Service | `planner/service.py` - every query filters on `user_id`; a foreign id is **404, never 403**; create / complete / skip / reopen / habit-log / reminder-act are **idempotent**; a completed / skipped / deleted / rescheduled / paused entity has its pending reminders cancelled in the same transaction; "Today" / pins / overdue are derived from the learner's local date |
| Reminder engine | `planner/scheduler.py`: ONE asyncio loop started from the app's `startup` hook (`run_forever`, 15 s), Postgres is the queue: `claim` (`FOR UPDATE SKIP LOCKED`) -> `deliver` (re-checks the entity / block / switch / pause **at send time**, quiet hours defer to the window's end, > 120 min late = shown in the app only, hourly cap 20, push with backoff 30 s / 2 min / 10 min then in-app only) -> follow-ups (default 1, 30 min apart, then `expired` - never endless) -> a 10-minute materializer (repeat tasks + timed habits, a rolling 48 h) -> daily prune. A delivery that died mid-flight is reclaimed after 2 min. The loop catches everything and logs class names only |
| Push (opt-in) | `planner/push.py`: VAPID keys generated once and kept in the `settings` table (`vapid_pub`, `vapid_priv`; or `VAPID_*` env), `pywebpush==1.14.1` + `py-vapid==1.9.2` + `http-ece==1.2.1` (**do not bump `cryptography==44.0.0`** - newer pywebpush / py-vapid need >= 46; it seals the BYOK keys). Subscription endpoints are allow-listed to the real push services (SSRF). Each push carries three **signed, single-purpose, 24 h tokens** (done / later / skip) so the notification buttons work with no login (`POST /planner/r/act`, 60 / min / IP behind `cf-connecting-ip`). `sw.js` v23 has `push` + `notificationclick`; a visible window gets a message instead of a second alert |
| API | `planner/api.py` - `/planner/today · summary · tasks (+ complete / reopen / skip / reschedule / pin / trigger) · goals (+ milestones) · habits (+ log) · due · reminders (+ act) · prefs · push/key|subscribe|test · export · delete-all · r/act` |
| DuSu knows the plan | `planner/life_lines.py` registers on `life.EXTRA_LINES` (providers may now take `(uid, email)`; the old one-argument form still works): today's plan, the routine in time order, habits, goals, the next reminder, and the rule "you can NOT add or change tasks from a chat". Home: `home_flags.planner` -> the model's catalogue offers My Day (id `goals_planning`), `_PLAN_RULE_ON`; with the switch off the registry card is honestly "Coming soon" |
| Client | `PL` module in `test_client.html` (one `#pl` screen: Today / Tasks / Goals / Habits tabs, 🔔 Reminders, ⚙ Settings, Add + edit sheets, an in-app reminder card on **any** screen, `pl-*` CSS only), routes `/my-day[/tasks|goals|habits|reminders|settings]`, Home card + More row + Home tile, Hindi / English via its own `TXT` table and the shared `LG` choice (default Hindi; the learner's own task titles are never translated). The ＋ is outside the screen on purpose: an animated `.screen` is the containing block of its fixed children |
| Data rights | `GET /planner/export` (JSON, no push keys), `POST /planner/delete-all {confirm:true}`, `db.delete_user` and `db.admin_wipe_users` delete the planner rows first (FKs) |
| Limits | 500 open tasks · 10 active goals · 30 habits · 12 steps per goal · 3 pins a day · 100 creates a day · 5 push devices · 20 pushes an hour |

**Not in this pass (so the copy never claims it):** AI parsing of a sentence, AI goal drafting / replanning, the recovery card, the evening review, voice capture of tasks ("DuSu, remind me ...") - DuSu **reads** the plan but never changes it. Mid-chat `Hindi / English` for DuSu's own wording follows the Home chat's rules.

**Update 2026-10-11 - the owner's first real use: four reminders saved, none of it visible (fixed).** Measured on prod: the 4 reminders and the goal were all in the database - the defects were what the screens showed and what DuSu was told. (1) **Reminders are part of the day**: `today()` carries `reminders` (the learner's own, still ahead; `reminder_brief` adds their LOCAL `day` / `time`) and `counts.reminders_today`; Today lists them in a "Reminders" section (a round check to tick one off, tap the words to change or delete it), the summary and the Home card count them, and a day with only reminders is no longer "Nothing planned". A new **Reminders tab** (five tabs now: Today / Reminders / Tasks / Goals / Habits - they share the row and stretch; only a ~320 px screen scrolls) groups by the learner's day, with History. Before, reminders were only under the 🔔 icon. (2) **Edit / delete**: `PATCH /planner/reminders/{id}` (words, day, time; a new time re-arms even a done / missed one) and `DELETE` (status `cancelled`, never fires - the scheduler re-checks the status at send time); only the learner's OWN note-to-self reminders (a task's, a habit's or a test reminder -> 404, like a foreign id); a **duplicate guard** (same words at the same minute, any case -> the one that exists, `duplicate: true`). (3) **Say what happened**: toasts with the exact time ("Reminder set for Sun, 11 Oct, 4:34 pm" / "already set" / "Task saved"); after saving a task the Tasks list switches to the view it landed in (Today / Upcoming / No date / Repeating) instead of an empty Today; a hint card on the Reminders tab while notifications are off ("you will only see these while DuSu is open", Turn on / Not now - production had 0 push devices for the owner). (4) **DuSu reads ALL reminders**: `life_lines.format_lines` lists every one (waiting for their tap / still ahead today / later, in time order) and no longer calls a day with reminders empty - it used to hand the model ONE "Next reminder" and "nothing is planned", so DuSu named the first and called the day empty; `_PLAN_RULE_ON` now says read EVERY one with its own words, never merge two ("at 8 PM, two: A and B") - the one case a Home reply may run past three sentences (reply clamp and token budget 900). (5) **Start Speaking tells the plan**: the client sends `plan: true` only on Start Speaking; the server builds one line with NO model (`life_lines.plan_text`, Hindi + English) and returns it in `home_ready.plan` - only when My Day is on for the learner AND the Home privacy switch is on; the client says it right after the greeting (the mic opens after it) or just shows it in text mode (`HM.tryPlan`); it is added to the transcript so the model knows it was said. **Verified (2026-10-11):** 84 pure checks, 160 scratch-Postgres checks (30 new: Today / summary / list shape, duplicate guard, PATCH / DELETE incl. past + bad input + foreign + task / test reminders, the scheduler never fires a deleted one, the 20-probe IDOR matrix, the plan line + the model's context), **46 real-stack checks** (real Chromium -> real HTTP / WebSocket -> the new code -> the real model, replaying the owner's session: three reminders through the + button, Today / Reminders / History, duplicate, edit, delete, done, task / habit / goal lists, Start Speaking says the plan in English and in Hindi, "what are my reminders?" -> the real model names all three incl. "two reminders for prayer"), the My Day look suite 69/69 (layout, accessibility, Hindi / English key parity), the Home suites 123 + 55 + 28 unchanged, and the old features' observations byte-identical (3 variants x 89). **Not verified:** push on a real phone (still), the spoken plan on a handset.

**Update 2026-10-11 (evening) - the second report: "I can't see all the lists, I should be able to edit and delete them, and I can't add new ones" (fixed).** Measured on prod (server log + rows), not guessed: (1) **first-use crash** - `_prefs()` was check-then-insert; the app's first load fires several requests at once (Today, the Home card's summary, the due list ...) and the losers died with `duplicate key ... pl_prefs_pkey` (HTTP 500, 9 tracebacks - a second learner's first load). Reproduced on a scratch DB: **12 of 12 first loads of a new learner had failing requests on the deployed code (70 failed requests), 0 of 12 after the fix**. Now `INSERT ... ON CONFLICT DO NOTHING`, savepoints around the other get-or-create inserts (a habit's first log of the day, a reminder's occurrence key), and the client retries a failed GET once. (2) **nine refused adds** - a reminder time that had already passed today was a 422 "That time has already passed", shown at the top of a tall sheet, so people tapped Save again. `timeutil.resolve_fire` now moves it to the NEXT such time (tomorrow), the response carries `rolled: true` and the toast says so; only an explicit day before yesterday is "past". The log now says which rule refused a request (`[planner] 422 create_custom_reminder: past` - never the words). The refusal message is pinned right above Save (a sticky footer, `role="alert"`) and the sheet lifts above the on-screen keyboard (`visualViewport`). (3) **ticked-off items vanished** - ticking a reminder dropped it from "Coming up" into a read-only History, so the owner (3 ticks) and the second learner (2) "could not see" them. Now the Reminders tab opens on **All** (`GET /reminders?view=all`: what is ahead + waiting + ticked + missed in the last 2 days), a ticked reminder STAYS (green tick, struck through) and un-ticks (`act reopen`: scheduled again if its time is ahead, else "due now"), Today lists today's ticked ones (`today().reminders_done`), History rows keep the tools; Tasks opens on **All** too. (4) **edit / delete / add are visible** - every task, reminder, habit (not the built-in English strip) and goal row carries a pencil and a bin (40 px+ targets, drawn icons, named for the item; delete asks first); a goal's pencil loads the FULL goal (the list does not carry why / minutes - saving from the list would have wiped them); a labelled "+ Add task / reminder / goal / habit" button under the tabs (the floating + stays). **Verified (2026-10-11):** 93 pure checks (`resolve_fire` incl. DST), 186 scratch-Postgres checks (26 new: 6 new learners x 9 parallel first requests, rolling, the All view, reopen, `reminders_done`, concurrent creates, the 422 log line), a real browser as a BRAND-NEW normal user 66/66 (first load, add every kind incl. a passed time, double tap, tick / undo, edit, delete, Hindi forms, a 360 x 640 phone with a fake on-screen keyboard, layout at 360 / 390 / 1280) with 0 tracebacks / 0 5xx / 0 422 in the 628-call server log, the owner replay 47/47 with the real model, the My Day look 69/69, the Home suites 123 + 55 + 28 unchanged and every old feature's observations byte-identical (3 x 89). **A bug the tests caught before it shipped:** a new `done_rows` variable in `today()` shadowed the done-TASKS list (a 500 for anyone with a ticked reminder). **Not verified:** a real phone's on-screen keyboard (simulated with a fake `visualViewport`), push when the app is closed.

**Gotchas:** the app's own day boundary is IST everywhere else; My Day uses the learner's zone (default `Asia/Kolkata`, auto-detect + a banner when the phone's zone really differs - `Asia/Calcutta` and `Asia/Kolkata` are the same zone and are compared by what they do). DST: a nonexistent local time lands one gap later (02:30 -> 03:30), an ambiguous one fires once (the earlier). The "English practice (DuSu)" habit is virtual - minutes come from `daily_stats` (IST day). In the scratch tests `main.planner_scheduler.run_forever` is the SAME object as `scheduler.run_forever`: keep a reference before replacing it or the "loop itself" test runs a no-op.

**Verified (2026-10-11):** `planner_unit.py` 66 pure checks (time / DST / recurrence / quiet hours / rules / tokens / SSRF / payload / registry); **scratch Postgres** `planner_selftest.py` 130 checks through the real HTTP layer + the real scheduler with a fake clock and a fake push sender (idempotency, cancel-on-complete / delete / reschedule / pause, quiet hours, stale, follow-ups then expiry, push accepted / gone / transient backoff / hourly cap, crash reclaim, concurrent claims are disjoint, a 17-probe **two-learner IDOR matrix** all 404, blocked account, export, delete-all, `delete_user`, owner wipe, DuSu's plan lines, Home wiring, the Know About card live vs "Coming soon", and **the loop itself delivering a reminder end to end**); **real browser -> real server -> real loop** `pl-e2e.cjs` 45/45 (task add / complete / reopen, repeat, condition button, habit glasses, goal steps + progress, a reminder delivered by the live scheduler and answered from the floating card, settings, export, isolation, delete-all, a deep link) and `pl-look.cjs` 69/69 on realistic data (every screen in Hindi and English at 360 / 390 px and desktop: no horizontal overflow, every control named, tap targets, key parity, reduced motion, the ＋ at the content column's corner); an old -> new schema migration rehearsal on a scratch DB (`mig_check.py`: exactly nine tables + partial unique indexes added, the existing user untouched, `init_db()` idempotent). **Not verified:** push when the app is closed (a real phone: Chrome tab / installed PWA / the Play TWA / battery killers) - nothing is promised until the owner runs Settings -> "Send me a test reminder" on the handset; Hindi wording on a real device.


**Update 2026-10-15 - repeating reminders: "add this reminder for Mon, Tue; this one for Saturday; once it is set it works forever" (built, verified and **DEPLOYED 2026-10-15 evening**).** Measured first, not guessed: everything was already stored in Postgres, and tasks (`recurrence` + series templates) and habits (`schedule.days`) already repeated on chosen weekdays - only a **reminder** was one-shot (`create_custom_reminder` makes ONE row). The fix is a new kind of reminder, not a change to the others.

| Piece | Where |
|---|---|
| **The rule** - what lasts | new table `pl_reminder_rules` (`models.PlReminderRule`: `user_id` FK, `client_key` partial-unique, `title`, `time` 'HH:MM', `days` JSONB `'daily'` or `[0..6]` (Mon = 0, the same shape as a habit's), `status` active / paused, `tz`) - brand new, `create_all` adds it, **no ALTER** (rehearsed old -> new schema). Hard-deleted with its rings withdrawn. Limit 30 per learner |
| **The rings** - what rings | ordinary `pl_reminders` rows, `entity_type 'custom'`, `kind 'recurring'`, `entity_id` = the rule, key `rr<rule>:<local day>:<HHMM>`, `meta {day, time, rule}`, made for **today + tomorrow** by `service._materialize_rule` (the habit pattern), called from `_materialize_user` (the scheduler's 10-minute pass, create, edit, resume-everything, a time-zone change). So claim / deliver / follow-ups / push + its Done-Later-Skip token / the in-app card / tick-undo / snooze all work **unchanged**. A time already passed today is simply not made (never moved or refused); `is_rule_occurrence(r)` tells a ring from a habit's row (also `kind recurring`) |
| Rules of the road | `_materialize_user` takes the rule rows `FOR UPDATE`, so an edit in flight and the materializer serialize (a test **forces** the bad interleaving). `scheduler._entity_check` re-checks at SEND time - rule exists, active, still rings on that day, same time - else the ring is cancelled "gone" (a ring claimed a moment before an edit / pause must not go off). **One ring cannot be edited or deleted on its own** (404): the materializer would simply make it again - the rule is the unit. Create is serialized per learner by an advisory lock (the duplicate + limit checks are check-then-insert). `_upsert_reminder` now also re-times a revived ring (`tz`) |
| API | `GET / POST /planner/reminder-rules`, `PATCH / DELETE /planner/reminder-rules/{id}` (PATCH: `title`, `time`, `days`, `action: pause / resume`). A retried create (same `client_key`, even with other words) and the same words + time + days return the rule that exists (`duplicate: true`). `today()` gains `repeating` (every rule with its own next ring - a Saturday-only rule shows its Saturday on a Monday, when no ring exists yet); rings carry `rule_id` + `repeat {days, status}`; `list_reminders` window 60 -> 150, `today().reminders` 12 -> 30 (rules add rows) |
| Client (`PL`) | the reminder form has **Repeat: Once / Every day / Selected days** (seven 44 px weekday chips, `aria-pressed`; the date hides); the Reminders tab opens with a **"Repeating reminders"** section (days · time, "Next: ...", a Paused chip, pencil / bin; pause / resume / delete in the edit sheet) because only two days of rings exist as rows; a ring row shows 🔁 + how often and its pencil / bin act on the RULE; a one-time reminder edited into a repeating one is replaced by the rule; toasts say exactly what was set and when it rings first; Hindi + English (neutral verb forms). `sw.js` v29 |
| DuSu knows | `life_lines` adds a "Repeating reminders (...)" line listing every rule whole (paused ones flagged) and no longer says "Reminders: none set" when only repeating ones exist |

**Also fixed (found while testing):** (1) `PL.onLang()` closed an open Add / Edit sheet every time `/me` answered - not only when the language changed - so a learner who opened the form in the first seconds on a slow connection lost what they had typed; it now closes only when the language the sheet was drawn in is no longer current (`sheetLang`). (2) Every planner endpoint answered **HTTP 500** for an id beyond a 32-bit integer (`/tasks/99999999999`, ...); `api._run` maps the database's `DataError` to 404 (the app itself never sends such an id).

**Verified (2026-10-15)** - a **new committed harness**, `tests/my_day/` (README there): `unit.py` **92** pure checks (`clean_days`, `days_scheduled`, `next_rule_fire` incl. DST / half-hour / +13 h zones and a 4 000-case property test against an independent oracle, column widths, the occurrence key, DuSu's lines incl. hostile titles); `run.sh selftest.py` **221** checks on a scratch Postgres through the real HTTP layer and the real `tick()` / `materialize_all()` / `deliver()` on a **fake clock**: the old -> new schema rehearsal, validation, IDOR + odd ids, the limit, **the promise (three rules set once, 28 days driven: every ring on its own weekdays, none on the others, none twice, the table does not grow)**, pause / resume / edit / delete, ring tick / snooze / skip / undo, follow-ups, push + the notification token, Today / list / summary, DuSu's context, time zones + DST both ways + pause-everything + quiet hours, concurrency (12 simultaneous creates, 8 materializers, an edit racing the materializer), tasks and habits repeating on weekdays, one-time reminders unchanged, export / delete-all / account deletion / the owner's wipe across **every** `pl_*` table; `mutants.sh` - 16 deliberate bugs planted one at a time in a copy of the backend (weekdays ignored, delete leaves rings, an IDOR, no lock, no send-time check, ...): **all 16 caught** (a 17th is an equivalent mutant, documented - the unique index backs the key check up; the first run found 4 weak spots in the TESTS - no create-while-paused check, no forced race, a no-op mutant - and they were closed); `browser/run_real.sh` **124** checks in a real Chromium against the real app (scratch Postgres, the **real reminder loop on the real clock**): the form, set-once for Mon + Tue / Saturday / every day, tick / change / pause / resume / delete, a one-time reminder made to repeat, Today, **a repeating reminder really rings (the live loop delivers it, the in-app card appears, Done ticks that ring and the next one is waiting)**, Hindi + key parity, layout at 360 / 390 / 1280 (screenshots reviewed), an XSS canary, isolation, no console error. Regressions: Resume Interview unit 309 + selftest 188, server old = old 87/87, the older browser suite (flow / edge / device / xss / static / looks / old-equals-old) unchanged. **Not verified:** a real phone (the on-screen keyboard, push when the app is closed - nothing is promised until the owner runs Settings -> "Send me a test reminder" on the handset), the Hindi wording on a real device.


**Deployed 2026-10-15 (evening)** - together with the Job Interview Practice update of section 16 (commits `13a53a3` + `60f49a4`; image `dusu-backend:latest` = `7616f1b32778`; `sw.js` = `dusu-v29`). Procedure and what was checked, so the next deploy can copy it: **rollback image** `dusu-backend:pre-repeating-reminders` (= the previous production image `4b7479bd5e94`; to roll back: `docker tag dusu-backend:pre-repeating-reminders dusu-backend:latest && docker compose up -d --no-deps backend` - the extra table `pl_reminder_rules` is harmless to leave) and a **pre-deploy dump** `~/dusu-backups/dusu-before-repeating-reminders-20261015-205532.sql.gz` (the owner may delete it - it is the only copy besides the live volume); `docker compose build backend` first, while the old container kept running; then the **built image itself** was tested, not the working tree: its files are **byte-identical** to the tested tree (a sha256 over every `.py` / `.html` / `.js` / `.txt`), `import app.main` is clean, `tests/my_day` ran against its baked code with `MD_BACKEND=baked MD_TEST_IMAGE=dusu-backend:latest` - **92 unit, 221 scratch-Postgres, 124 real-browser (a repeating reminder really rang)** all pass; then `docker compose up -d --no-deps backend` (only the backend container is recreated; downtime = the few seconds the new one takes to become healthy). **Live check:** startup log clean, `init_db()` created `pl_reminder_rules` + its 4 indexes (0 rows), every row count identical before / after (18 users, 10 reminders, 1 goal, 1 interview, 3 documents), all six rollout switches still `on`, the reminder queue healthy (0 overdue, 0 stuck mid-send), `sw.js` = `dusu-v29` and the page carries the new code on `localhost:3878`, `dusu.ranabrothers.online` and `dusu.ruralrootcloud.com`, `/planner/reminder-rules`, `/planner/today` and `/rinterview/state` answer 401 without a login on all three. Nothing was written to production by the checks (read-only queries and unauthenticated GETs). **Not pushed to GitHub.**


**Update 2026-10-15 (night) - "I can check but I cannot uncheck" (fixed; the owner: *in My Day a user must be able to check AND uncheck reminders, goals, habits and tasks - I checked for testing and then could not uncheck*).** Measured first, not guessed: the server log of that session reads POST habit -> PUT log -> PATCH habit -> PUT log x3 -> DELETE habit, **every tap answered 200 and changed nothing** (`pl_habit_logs` still `count = 1`, one `logged` event). So the server was fine - **a client bug**: each My Day tab refreshes only ITS OWN list (`D.tasks`, `D.habits`, `D.today`, `D.rem`) and the decision "check or uncheck?" was made at CLICK time by `findTask` / `findHabit`, which returned the FIRST list holding the id - the Tasks / Habits tab's list, before Today's. After visiting the Habits (or Tasks) tab and then using Today, that first list was out of date: a second tap saw "not checked" and re-sent "check". (Reminders and goal steps were not affected - they decide when drawn.) Driving every place with real clicks found three more gaps: a task checked on the Tasks tab **vanished** from All and Today (it waited in the Done chip, where nobody looked); a goal had **no check on its row** (only a Done button inside it); a once-a-day habit showed a numbered glass "1" and nothing said how to take a tap back.

| What | How |
|---|---|
| Decide when DRAWN, never guess later | a task / goal circle carries `data-do` (`complete` / `reopen` / `done`), a habit button carries `data-set` (the exact count the tap sets) - computed from the row being drawn, so what a tap does is what the screen shows; the calls are absolute and idempotent, so a fast double tap cannot flip twice. Reminders already worked this way (`remdone` / `remreopen`) |
| The freshest copy wins | `stamp(k)` on every list load, `pick(id, pools)` returns the hit from the NEWEST list: `findTask` / `findHabit` / `findRem` no longer hand an edit sheet an old copy either |
| Tasks | `list_tasks`: **All** = open + finished / skipped in the last 2 days (after the open ones, struck through), **Today** chip = + finished today; older ones are in the Done chip (14 days) and are uncheckable there; a skipped task's circle puts it back; a finished / skipped task's sheet offers **Reopen**; on the Today screen a check says where the task went ("moved to Done today - tap its circle there to undo") |
| Goals | a **check circle on every goal row** in the Goals tab (`gchk` -> `PATCH /goals/{id} {action: done / reopen}`; a reopened goal's `completed_at` is cleared); the steps inside a goal and Done / Reopen are unchanged |
| Habits | once a day = a labelled check ("Mark done today" / "Done today - tap to undo", `aria-pressed`); 2-8 a day = numbered glasses (tap glass k sets k, tap the last filled one takes one back) + an explicit **Undo**; more = `-` / `+` |
| Reminders | logic unchanged; the "Coming up" chip (a ticked reminder leaves it) now says it is under All and how to undo |
| Shell | `sw.js` `dusu-v30`; new strings in English + Hindi (neutral verb forms), key parity checked |

**Verified (2026-10-15 night):** a **reproduction first** - `tests/my_day/browser/checks.spec.cjs` against a copy of the code that was live: **43 checks fail** (the habit's second tap, the glass rules, the vanishing task, the stale-copy sequence on tasks and habits, the missing goal check, the missing Undo ...), the same spec on the fix: **137 / 137** (habits made on one tab and checked on another, glasses, an edit in between; tasks on All / Today / Done, skipped, a repeating occurrence, one finished five days ago; goals' row check, steps, Done / Reopen; reminders on All / Today / Coming up / History incl. one ticked four days ago; Hindi + accessible names; layout at 360 / 390 / 1280); `selftest.py` **293** (72 new, a "check and uncheck" section: the lists after a check, a check twice, skip, time passing - two days, a new day, two weeks - goals incl. `completed_at`, steps, habits' absolute counts incl. skip and a past day, reminders from History, and another learner getting 404 everywhere); `mutants.sh` M18-M20 (the vanishing list, a stale finished-at, a window that never closes) all caught; unit 92; Resume Interview unit 309 + selftest 188 + server old = old 87/87; the older browser suite unchanged. **Not verified:** a real phone.


**Deployed 2026-10-15 (night)** - commit `1ec88cf`, image `dusu-backend:latest` = `7a44bd5507e1`, `sw.js` = `dusu-v30`. Same procedure as the repeating-reminders deploy above: **rollback image** `dusu-backend:pre-check-uncheck` (= the previous production image `7616f1b32778`; `docker tag dusu-backend:pre-check-uncheck dusu-backend:latest && docker compose up -d --no-deps backend`; no schema change, so nothing else to undo) and a **pre-deploy dump** `~/dusu-backups/dusu-before-check-uncheck-20261015-215730.sql.gz`; the image was built while the old container kept running, then tested **as built**: its files byte-identical to the tested tree, `tests/my_day` against its baked code - unit 92, scratch Postgres **293**, real browser **137** (`checks.spec.cjs`) and **122** (`real.spec.cjs`; two of its checks are time-gated and skip after 21:00 India time) - then `docker compose up -d --no-deps backend`. **Live check:** clean start, every row count and all six rollout switches identical before / after, the reminder queue healthy (0 overdue, 0 stuck), `sw.js` = `dusu-v30` and the page carries the new code (`gchk`, `pl-hcheck`) on `localhost:3878`, `dusu.ranabrothers.online` and `dusu.ruralrootcloud.com`, `/planner/today` and `/planner/tasks` answer 401 without a login on all three. The checks wrote nothing to production. **Test gotcha learned:** the default quiet hours (22:00-07:00 in the learner's zone) correctly hold a reminder back, so a test that waits for a REAL ring after 22:00 India time must turn quiet hours off for its learner (`PUT /planner/prefs {quiet_on:false}`) - the first baked run of `real.spec.cjs` failed at 22:04 for exactly that reason. **Not pushed to GitHub.**

---

## 15. Early access - show a staged feature to named accounts (built 2026-10-11)

**Why it exists.** Every new feature ships behind a rollout switch (`practice_room`, `planner`, `home_ai`, `bilingual`, `life_context`) set to `owner`. A second account ("Vijeta Rana", a normal `user`) could not see ANY of the new features - not a bug: the switch said "owner only" and `role_for()` said "user" (measured on prod 2026-10-11: all five `*_enabled(email)` returned False for her and True for the owner; she was past the own-keys wall, with verified keys). There was no way to show a feature to one person short of flipping it for all 17 accounts.

| Piece | Where |
|---|---|
| List | table `early_access_emails` (email PK, lowercased; `added_at`) - a brand-new table, no migration. `db.early_list / early_has / early_add / early_remove` (`early_add` -> `added` / `exists` / `invalid` / `full`, cap `_MAX_EARLY` = 100); `_clean_email` |
| Gate | `main.staged_visible(email)` = the owner / unlimited role **or** the email is on the list (`early_access`, cached 60 s like `is_office`). The five `*_enabled` functions use it for mode `owner`. `off` stays off for everyone (a kill switch); `on` = everyone |
| Owner UI | dashboard -> Access -> **Early access (testers)** (list, add, remove) + a **Give / Remove early access** button and a 🧪 tag on every user card; the switches' middle option now reads "Owner + early access". `/admin/overview` carries `early_access` + `users[].early`; `POST /admin/early {email, action}` (owner only; 400 on a bad email or a full list) drops the access cache, so the tester's next `/me` already has the features |
| What it does NOT do | **visibility only** - `role_for`, `resolve_keys`, `is_unlimited`, `is_office` never read the list: no admin, no free keys, no quota (a tester still meets the own-keys wall - tested equal to a normal account). `UNLIMITED_EMAILS` is NOT a substitute: it would also hand the person the server's keys with no quota |
| Data hygiene | `delete_user` (the owner's Delete AND a learner deleting their own account) removes the row - an email is personal data; "Reset test users" keeps invited testers |
| Granting without the dashboard | a `.sql` file piped into `dusu-db-1`: `INSERT INTO early_access_emails (email, added_at) VALUES ('person@example.com', now()) ON CONFLICT DO NOTHING;` - visible within the 60 s cache |

**Gotchas:** the tester has to reload / reopen the app (the flags come with `/me` at load; an installed PWA / TWA may need a full close). A dashboard change is immediate on the server; direct SQL waits out the cache (up to 60 s). **Verified (2026-10-11):** 48 scratch-DB checks through the real HTTP layer + WebSocket - the bug reproduced first (all five features invisible to a normal account), then after the invite visible to the tester only, no admin / keys / quota leak, `off` still hides, `on` still means everyone, validation, idempotency, cap, the cache path, delete / wipe / self-deletion - and 45 Chromium checks on the dashboard at 360 / 390 / 1280 px (mocked owner API) plus a look at the screenshots. **Not verified:** the tester's own phone (reload behaviour of the installed app).

---

## 16. Job Interview Practice (code name Resume Interview) - resume + job description -> a recorded mock interview (built 2026-10-15 - design + status in `DUSU_RESUME_INTERVIEW_PLAN.md`)

> **Name.** Shown to learners as **Job Interview Practice** (renamed 2026-10-15 at the owner's request, so it cannot be confused with "Interview Prep", the general HR mock). Everything internal keeps the old name on purpose: the switch `resume_interview`, `backend/app/resume_interview/`, `ri_*` tables, `/rinterview/*`, the route `/resume-interview`, the `RI` module, `#ri*` ids. Older paragraphs below say "Resume Interview" - same feature.

The owner's request: upload a resume, upload a job description, DuSu shows the mismatches and how to improve the resume (re-upload or continue), then interviews them for that job; after each question the answer is recorded, they can listen to themselves back, DuSu names the mistakes, they tap Next; **Finish** unlocks after 3 questions and shows a full report; "all should be kept in the DB, full system sync". **Rollout switch:** `settings.resume_interview` = `off` (code default) / `owner` (owner + early access) / `on`, flipped from dashboard -> Access -> "Resume Interview" - **set to `on` (everyone) on 2026-10-15 at the owner's request, before any real-phone check** (visible from the learner's next page load; rollback = set it to Off, live within 60 s); `/me.resume_interview`; every `/rinterview/*` endpoint answers 404 while it is off for the account (export / delete-all excepted). **Deployed 2026-10-15** (commit `0c5038b`, local - not pushed; rebuilt because `requirements.txt` gained `pypdf==6.20.1`; first deployed dark, then switched on): tables created, 0 rows at deploy time, `settings` row absent until the switch was set, `/rinterview/*` answers 401 without a login on localhost and both public hostnames, `sw.js` = `dusu-v27`. Rollback image `dusu-backend:pre-resume-interview`; pre-deploy DB dump in `~/dusu-backups/` (delete when satisfied). Details: plan 19.7.

| Piece | Where |
|---|---|
| Package | `backend/app/resume_interview/`: `rules.py` (pure: limits, cleaning, requirement / evidence checks, match score, question validation + a bank of 36, per-answer scoring, the computed report), `docs.py` + `extract_child.py` (upload -> sandboxed extraction -> clean -> redact), `prompts.py` (4 prompts, all data fenced with per-call random tokens), `engine.py` (model calls with a retry ladder: full schema -> compact schema -> deterministic), `models.py`, `service.py` (all DB logic), `api.py` (router `/rinterview`, 22 routes), `life_lines.py` |
| Tables (new only - `create_all`, no ALTER) | `ri_documents` (immutable, redacted text, version chain by `parent_id`, **no filename stored**) · `ri_analyses` (one per resume x job; `state` + `claimed_at`; `result` JSONB) · `ri_sessions` (draft -> matched -> active -> finished; `plan_state`; **`awarded_at` = XP exactly once**; `rev`) · `ri_turns` (the plan is ROWS: queued -> asked -> answered / skipped / dropped; transcript, metrics, feedback JSONB, `feedback_state`). No stored counters: asked / answered / real are `GROUP BY` under the session lock |
| Documents | raw-body upload (no `python-multipart`; the name travels in `X-RI-Name` and is not stored), sniffed by magic bytes (PDF / DOCX / text; legacy `.doc` -> "save as .docx"), extracted in a **child process** (`python -I -B extract_child.py`, EMPTY environment, rlimits, drops to `nobody`, 12 s wall kill, 2 at a time; PDF = `pypdf`, first 8 pages; DOCX = stdlib `zipfile` + regex), cleaned (NFKC, ligatures, control characters and lone surrogates out) and **redacted** (email / phone / links -> typed placeholders, Aadhaar only if Verhoeff-valid, PAN, a name-like first line, "Personal details / Declaration" blocks). The learner sees what was kept and removed and taps **Looks right**. Best effort - the privacy page says so |
| Model calls | **A** job -> <= 10 requirements (cached in the job's `meta`) · **B** resume x requirements -> status + evidence + <= 5 edits (cached per resume sha, job sha, `RULES_VERSION`) · **C** brief + ~12 questions at **Start** · **D** per-answer feedback (temperature 0.2). **Finish makes no model call.** Each call: input + cap <= ~6 k tokens |
| Computed, not guessed | match score = sum(weight x status) / sum(weight) (must 3, nice 1; met 1, partial 1/2); `met` needs evidence found in the resume by a ladder (normalised -> compact -> token overlap >= 0.8), else `partial`, **never** `missing`; per answer 5 categories (relevance 25, specificity 20, structure 15, language 20, delivery 20): anchored 1-5 model judgements (22 / 42 / 62 / 78 / 92) blended with code-computed evidence, delivery measured from word timestamps (Gemini has none -> "not measured", never mixed with measured); a mistake is shown only if its quote is found in the transcript; a "stronger answer" number must occur in the transcript / resume / job or it is bracketed; a REAL answer = >= 25 words, >= 10 s, <= 230 wpm, not a Whisper silence hallucination. Per-answer feedback shows **bands**; numbers only in aggregates |
| Concurrency | the **claim pattern**: lock -> validate -> `*_state='pending'` + `claimed_at` -> commit -> model call with NO transaction -> lock -> write only if the claim is still ours. A duplicate gets `202 {pending:true}` and the client polls the matching `GET`; a claim is stale after 60 s. `next` is idempotent; an answer replays by `answer_key`; Finish locks once, drops queued turns and refuses late writes; minutes = sum(min(answer_sec, 185)) / 60 |
| Sync with the rest | `award_speaker_progress(uid, "resume_interview", ...)` + `update_weekly_missions` + `bump_daily_stat` + `add_vocab` (`_MODE_BONUS["resume_interview"]` = 25) · one cleaned line via `add_conversation` (**no** `set_next_hook`, never resume text) · `life.EXTRA_LINES` provider -> DuSu's "knows your data" block (scores + role title only) · `home_content.FEATURES` entry (id `resume_interview`, route `/resume-interview`, `needs:"resume_interview"`) -> Know About, the Home tile, the model's catalogue (**`_KW` / `_DEFAULT_SUGGEST` are NOT touched**) · `/me` adds `resume_interview` + `ri_server_stt` · `/admin/overview` adds `resume_interview_health` |
| Client | `RI` module in `test_client.html` (after `PL`): one screen `#ri`, views hub / resume / job / analysing / match / interview / report / settings, a URL per step (`/resume-interview[/resume\|job\|match\|interview\|report\|settings]`). **No `innerHTML` (or any HTML-injecting API) in the module** - a small allow-listed DOM builder `h()`. Recorder adapted from the Practice Room's (webm / opus 24 kbps, 10 s chunks mirrored to IndexedDB `dusu-interview`, wake lock; Back, a phone call or a hidden tab **keep** the take). **Audio stays on the phone** (tagged with the account; `RI.wipeLocal()` on account deletion). Speech-to-text = the learner's own Groq key straight from the phone (with a vocabulary prompt), else `POST /rinterview/transcribe` (Groq -> Gemini). Entry points `#riEntry` (Practice hub), `#riHomeCard`, More row `#mrowRI`; `sw.js` cache `dusu-v27` |
| Data rights | `GET /rinterview/export`, `POST /rinterview/delete-all {confirm:true}`, per-document / per-interview delete; `db.delete_user` + `db.admin_wipe_users` call `service.delete_rows` (child-first); `privacy.html`, `terms.html`, `account-deletion.html` updated (resume / job / transcripts ARE stored; the file and the audio are not) |
| Shared-code edits (each reviewed) | `db.py`: `hide_parameters=True` (an exception's text never carries bound values), `_MODE_BONUS`, the delete hooks · `openrouter_provider._mark_cooldown`: rate-limit text wins and 401 / 403 / 404 / 410 match on word boundaries (a Groq 429 that said "Used 4041" used to cool Groq down **6 hours for everyone**) · `main.py` / `home_content.py` / `life.py` additive · `.gitignore` `**/.env.bak*` + `backend/.dockerignore` `.env.*` (the backup env files were being baked into the image) |

**Gotchas:** "Interview Prep" is the generic HR mock (`/interview`); this is **Resume Interview** (`/resume-interview`, API `/rinterview`) - the API prefix and the client route must differ because of the SPA fallback. The redactor removes a "PERSONAL DETAILS / DECLARATION" block **to the next heading or the end of the text** - anything appended after one is gone (a test payload vanished for exactly this reason). **Finish counts real ANSWERS, not feedbacks**, so a model outage cannot trap a learner. The cooldown map is process-global: one learner's burst can cool a provider for everyone, hence ~9 small calls per interview and the daily caps. `create_all` creates tables only - a column added later to an `ri_*` table needs an explicit `ALTER TABLE ... IF NOT EXISTS` in `init_db`; anything that may evolve belongs in JSONB with `rules_version`. The chain treats "all providers/models unavailable" as quota (429 `quota`) - use another message to exercise the 502 path. **Test harness gotchas (`tests/resume_interview/`, README inside):** an `http://<container-name>` origin is an insecure context with **no `navigator.mediaDevices`** (no microphone) - the real-server browser tier runs Chromium in the server container's network namespace (`--network container:...`) so the page is `http://localhost:8000` (production is https); the shell routes a cold deep link twice (cached state, then `/me`), so `#ri` is rebuilt - read the DOM in one step; the client's own-keys gate needs `dusu_keys_owner` = the account's email plus two keys in a test seed; the harness blanks every provider key (`run.sh`) because the bind-mounted `backend/` holds the real `.env` (the first draft of tier 2 made real calls); Docker here can only bind-mount paths under the repo, not `/tmp`.

**Independent review (2026-10-15) - what it changed.** A fresh agent read the backend adversarially: 24 findings, each reproduced before acting and pinned by a test that fails on the old code. Worth remembering: (1) **every regex that touches user text must be bounded and anchored, and the input sliced BEFORE any pass** - the first redactor took 11.8 s on an 8 KB paste, on the ONE worker's event loop (the unit tier now times 25 adversarial shapes x 7 entry points; slowest 90 ms); (2) a parse slot must be bounded in time AND in waiting (CPU 5 s, wall 8 s, a 3 s wait for a slot, one upload per learner); (3) redaction is **idempotent** - removed names / header addresses become `[NAME]` / `[ADDRESS]` placeholders, and both are searched AFTER the personal blocks are removed (fuzzed once on 16 000 random resume-like documents - no exception, `redact(redact(x)) == redact(x)` - and a seeded 3 000-document version of that property test stays in the unit tier); (4) an unmeasured component is UNSCORED, never 0 - a finished interview with no judged answer has `overall: null` and the screen says "Not scored"; (5) a "better answer" may only use numbers from the learner's own transcript and resume, never the job description's; (6) claim TTL 150 s, `force` removed, `/state.active` has its own query and `has_more` exists. Left on purpose (plan 19.3): the daily caps are derived from rows, so deleting an interview resets them (`charge_request` still bounds model spend); Finish while a feedback call is in flight freezes that answer's feedback; measured and unmeasured delivery are mixed in one overall; the per-IP limiter trusts `cf-connecting-ip` like My Day's.

**Verified (2026-10-15):** unit 281 · scratch Postgres + the real HTTP layer 174 (an old-to-new schema rehearsal, duplicate requests = one model call, XP once, the two-learner 404 matrix, claims, outages, awards, limits, data rights, introspection) · old = old (server) 87 vs `HEAD` · **real model**, default chain and Gemini-only, 34 / 34 each (strong answers 91-94 vs weak 49-50, every attempt < 20 s) · browser, mock server, 1 427 (flow, edge cases, two phones, XSS canary, static / hygiene, looks at 360 / 390 / 1280 px, **old = old including pixels**) · **browser against the real app + scratch Postgres** 68 (the journey, a second device, isolation, a learner's own Groq key, the XSS canary, the AI-down-for-every-answer path) · `import app.main`; `pip install --dry-run` on `python:3.12.7-slim`. **Not verified:** a real phone / the TWA microphone (permission, codecs, Wake Lock, the on-screen keyboard), real resumes and real Indian-English speech through Whisper / Gemini (plan spikes S1 / S2), Play's Data-safety form, Hindi screens (English in v1), a real-phone run on the deployed build. Remaining go-live steps: plan section 19.6 (3-5).

**Update 2026-10-15 (evening) - detailed saved reports, an improvement plan, "did it work?" (owner's request: "see my reports later, explain my weaknesses in detail, so in the next interview I improve them").** One new PURE module, `backend/app/resume_interview/coach.py` (no database, no network, no model - every sentence is a fixed catalogue text in English + Hinglish or a counted fact from the learner's own answers), adds report **v2** fields to the stored report: `v: 2`, `habits` (style habits counted per interview: no number / no result / short / no tool named / fillers per 100 words / pace / long pauses / a repeating grammar slip - they do not depend on WHICH questions were asked, so two interviews for two jobs can be compared), `weaknesses` (up to 5 ranked cards: what was seen, why it matters, 3 steps, a drill, the goal, the answers it happened in, the learner's own slips with fixes, the learner's own stronger answer as a model, unmet job requirements by name), `focus` (up to 3 improvement points, habits first because they can be checked), `progress` (the NEXT interview's report: each saved focus point of the previous interview judged better / same / worse with the real numbers, a 25-point noise band on rates, "too few answers" -> no verdict). Where it plugs in: `service.finish` builds it; **`_ensure_v2` upgrades an old-format report the first time it is read** (computed from the stored answers, saved, idempotent - this is how the first real interview, finished before the feature existed, got its weaknesses); `/state.focus` = the latest finished interview's points (the hub card); `GET /sessions/{id}.focus_prev` on an interview in progress = the previous interview's points (the focus bar before the first question and the per-answer check); `life_data` / DuSu's life line add the focus titles. Client: the report shows "Since your last interview" -> "Your improvement plan" -> the usual bars -> "Your weaknesses, in detail" (collapsible, the first open) -> "Question by question" where **every answered question expands** to what was said, what worked, mistakes, fixes, the stronger answer and the delivery numbers (read from `GET /sessions/{id}.turns`, no extra call); the hub has a "Your focus for next time" card; the match screen and the interview show the focus points; each answer's feedback carries a tick / cross per focus point, computed client-side from `feedback.evidence` / delivery / mistakes (so it also works when the AI was down). **Gotchas:** the ▶ Listen button lives in `.ri-pq-a`, OUTSIDE the collapsed answer (the details body has its own buttons) - specs count `.ri-pq-a .btn`; `redact`-style idempotence matters here too (`enrich_report(enrich_report(x)) == enrich_report(x)`); only HABITS are compared across interviews, never the five category scores (the questions differ); an interview with no weak spot shows "Nothing stands out" and sets no focus points; **"old = old" is now measured against `70455da`** (the last commit before the feature - `HEAD` already contains it): `run-all.sh` and the parity README use that revision. **Verified (2026-10-15):** unit 309 · scratch Postgres 188 (a weak first interview -> weaknesses + focus saved -> the hub's state -> `focus_prev` on the next interview -> an improved second report with `progress` -> an old-format report upgraded on read, no model call, saved) · parity 87 vs `70455da` · browser, mock server 1 518 (new `coach.spec.cjs` 65, incl. an old-format report and an interview with nothing to fix; XSS canary 123 now covers every new string) · **browser against the real app 90** (part G: a weak interview, then a strong one) · a dry run of the upgrade on the one real finished interview (5 ranked weaknesses, 3 focus points, original fields untouched). **Not verified:** how the new report reads on a real phone, and whether the Hinglish wording of the catalogue sounds natural to a native speaker (it follows the house rule: Roman letters, tum / aap, never tu).


**Deployed 2026-10-15 (evening):** the rename + the detailed reports / improvement plan / progress shipped in the same deploy as My Day's repeating reminders (see section 14 - image `7616f1b32778`, rollback image `dusu-backend:pre-repeating-reminders`, dump `~/dusu-backups/dusu-before-repeating-reminders-20261015-205532.sql.gz`). The `resume_interview` switch was already `on` for everyone, so learners see "Job Interview Practice" and the new report on their next page load; the one existing finished interview upgrades to the v2 report the first time it is opened (computed from its stored answers, no model call).

---

## 17. Grammar Coach - every English sentence checked, corrected, explained (built 2026-10-16, DEPLOYED DARK 2026-10-16 - design + status in `DUSU_GRAMMAR_COACH_PLAN.md`)

When the learner speaks ENGLISH in Face-to-Face (`conversation`), Interview Prep, the Practice Room (all kinds) and Job Interview Practice, DuSu checks every sentence **after the session** and shows a Grammar report (said -> corrected -> why -> rule -> why Hindi speakers slip, a Flow read) plus a separate **Grammar section** (`/grammar`: Overview / Mistakes / Sentences / Practice / Rules + settings). Hindi / Hinglish is never judged. **Ships dark (set to `on` for everyone 2026-10-16):** switch `settings.grammar_coach` = off (code default) / owner (+ early access) / on, set from dashboard -> Access; `/me.grammar_coach`; every `/gcoach/*` endpoint answers 404 while it is off for the account (export / delete-all excepted).

| Piece | Where |
|---|---|
| Engine (pure + ONE async AI stage) | `backend/app/grammar/`: `text`, `segment`, `gating` (+ `lexicon_lang`), `catalog` + `catalog_data` (41 rules, English + Hinglish), `detectors` + `lexicon` (19 rule checks D1-D16, T1-T3), `prompts`, `verify`, `engine`, `budget`, `scoring`, `flow` |
| Storage / API / wiring | `models` (new tables `gc_sessions`, `gc_sentences`, `gc_marks`, `gc_drills` - no ALTER), `service`, `api` (`/gcoach/*`), `tracker` (the detached retained task) |
| Hooks in shared code (all additive or switch-gated) | `main.py`: switch triplet, `/me`, admin, `_home_flags`, WS `start` reads a validated `gref`, `_persist_session` / `_practice_finish` start the detached analysis, `grammar_ref` added to `speaker_progress` / interview `report` / `practice_report` (no new frame types) · `db.py` + `resume_interview/service.py`: delete cascades (account, wipe, Practice attempt incl. pruned, interview) · `openrouter_provider`: additive `first=` and `cool=` · `home_content`: one FEATURES entry · `sw.js` `dusu-v31` · `privacy` / `terms` / `account-deletion` pages |
| Client | `GC` module in `test_client.html` (DOM-builder only, no innerHTML; `gc-*` CSS; body-level sheet; routes `/grammar[/mistakes\|sentences\|practice\|rules\|settings]`); summary card mounted in Session complete, the interview report, the Practice report and the Job Interview Practice report |

**Rules that make it trustworthy.** Precision over recall: a sentence is "no mistake found" only on a model verdict (rule checks add errors, never certify clean); the corrected sentence is BUILT BY CODE from verified `quote -> fix` edits (the model never rewrites); anything the code cannot locate / bound is dropped; speech-to-text artifacts (case, punctuation, homophones, numerals) are never flagged; on Chrome text a finding no rule check backs is only "likely" (soft, uncounted, never applied); Indianisms are tips, never errors. The headline is **mistakes per 100 words** with "N of M sentences with no mistake found" beside it - withheld below 6 checked sentences / 40 words; deltas only with >= 40 checked sentences per window; no composite score. **Existing score numbers are untouched** (`grammar_trend`, the interview Grammar bar, Practice's grammar bar). **Privacy:** only mistaken sentences are stored, only after the learner's one-time "keep / counts only" choice (until then the result is held in memory <= 30 min and only counts are written); `redact_light` on stored text; transcripts and audio are never stored. **Cost:** ~1 AI call per 12 sentences (<= 10 per session, one `charge_request`), `cool=False` (a grammar 429 never cools a provider for everyone's chat), skipped while any provider is cooling, process-wide semaphore of 2.

**Verified 2026-10-16 (scratch infrastructure only):** unit 4,036 checks (incl. 1,946 for the rule checks); the rule checks give **no false positive on any of 318 clean gold sentences** (`solo_gold.py`); scratch Postgres 88; WebSocket harness 18 (switch OFF vs ON identical except the additive keys; dropped sockets analysed; Hindi never); real Chromium against the real app 40; client old = old 28 (45 pixel-identical screenshots incl. session / session result / interview report); 24 planted bugs, all caught; Resume Interview (309 + 188) and My Day (92 + 293) regression suites unchanged. **Not verified:** the real-model gold-set gate (`tests/grammar/real_model.py`, owner-run - sends only synthetic sentences but uses the owner's free-tier quota), real phone speech-to-text (plan spike S1), Hinglish wording by a native speaker, the first-use notice and report on a handset, Play's Data-safety form. **Committed and deployed dark (not pushed).** Go-live order: policy pages ship WITH the code, switch to `owner`, run the owner checklist (plan section 12), then the real-model gate, then `on`.

**Not in v1 (the copy never claims it):** live notes under each message, the AI "smoother way to say it", more drill types + spaced repetition, a Home / My Day grammar block, `rules_disabled`, spoken recasts, Hindi screens.

**Deployed 2026-10-16 (dark at first; switched to EVERYONE the same day at the owner's request, before the real-model gold-set gate, a real-phone run or a native Hinglish read - rollback = set the switch to Off in the dashboard, live within ~60 s)** - commit `84890fd`, image `dusu-backend:latest` = `7f7b1cd961e9`, `sw.js` = `dusu-v31`. Same procedure as section 14: **rollback image** `dusu-backend:pre-grammar-coach` (= `7a44bd5507e1`; `docker tag dusu-backend:pre-grammar-coach dusu-backend:latest && docker compose up -d --no-deps backend`; the four empty `gc_*` tables are harmless to leave), pre-deploy dump `~/dusu-backups/dusu-before-grammar-coach-20261016-100911.sql.gz`; the image was built while the old container ran, then tested AS BUILT (files sha256-identical to the tested tree, `import app.main` clean, selftest 88 / WS harness 18 / real browser 40 against its baked code via `GC_BACKEND_DIR=baked GC_TEST_IMAGE=dusu-backend:latest tests/grammar/run.sh ...` and `GC_BACKEND=baked ... browser/run_real.sh`). **Live check:** clean start, `init_db()` created `gc_sessions / gc_sentences / gc_marks / gc_drills` (0 rows), every other row count and all six rollout switches identical before / after (no `grammar_coach` row = off), `sw.js` v31 and the new code on localhost + both public hostnames, `/gcoach/state` answers 401 without a login on all three. Nothing was written to production by the checks. **To turn it on:** owner dashboard -> Access -> "Grammar Coach" -> Owner + early access (the policy pages already shipped with the code), run the owner checklist, then the real-model gate, then Everyone. **Not pushed to GitHub.**

---

## 18. Notifications - personal nudges as push, in the Android app too (built 2026-10-20, ships DARK - plan in `~/.claude/plans/velvety-wishing-corbato.md`)

Before: the Android app fired the SAME static message every 4 hours from an `AlarmManager` alarm (not personal, ignored whether the learner practised, could not be turned off in-app, used the coloured launcher icon as its small icon so Android drew a grey square). The only real push was My Day's reminders, and `pl_push_subs` had **0 rows** in production - nobody had ever subscribed, and the TWA had no notification delegation, so it had never been proven inside the app. Now the server decides **what** to say and **when** from the learner's own rows, and the phone shows it as a DuSu notification.

**Pipeline:** Web Push only (one pipeline for browser, PWA and the Android app). Inside the app, `DelegationService` (TWA notification delegation) makes Chrome hand the notification to the DuSu app, so the Android permission dialog, the channel and the notification belong to DuSu. **No native Firebase**: a TWA has no JS bridge, so an FCM token could not be tied to a login without a custom install-ID hack, a new Firebase project and a server service-account secret. FCM stays a contingency, to be decided from the delivery numbers on the dashboard (accepted vs arrived vs opened).

| Piece | Where |
|---|---|
| Pure rules (no DB / network / clock except an argument) | `backend/app/notify/rules.py`: `slots()` (a send slot is open from 20 min before to 90 min after the learner's time, on THEIR clock), `plan_today()`, `pick_daily_kind()` (**streak beats practice, one slot a day**), `weekly_due()`, `is_paused()` (three ignored nudges -> a week's rest unless they opened one or practised since), `still_wanted()` (the SEND-time re-check), `render()` (Hindi default, English if `lang_pref` is `en`; deterministic wording per learner per day; lock-screen privacy -> generic text), `build_payload()` |
| Tables (both NEW, no ALTER) | `nt_prefs` (`enabled`, `kinds` {practice, streak, weekly}, `nudge_time` 'HH:MM', default 19:00) and `nt_outbox` (one row per notification: `kind`, `dedupe_key` **unique per learner** = "one nudge a day / one weekly note a week" enforced by the database, `fire_at`, `title/body` written at SEND time from the facts as they are then, `status` scheduled/sending/sent/cancelled, `why`, `push_state`, `received_at` = the phone said it arrived, `opened_at` = tapped, `meta`). Time zone, quiet hours and lock-screen privacy are My Day's `pl_prefs` (one place); devices are My Day's `pl_push_subs`; the sender is `planner.push.send` |
| What is sent (no model call, no cost) | **streak**: streak >= 2 alive (last active today / yesterday, IST) and nothing done today -> at their time. **practice**: onboarded, nothing today, no live streak. **weekly**: Sunday 10:00 local, `xp >= 20`, active in the last 7 days, last letter >= 7 days old (the letter itself is only generated when they open it). Cancelled at send time if they practised meanwhile, quiet hours, switched off, blocked, > 90 min late (never a stale nudge), paused |
| Engine | `notify/scheduler.py`: a SEPARATE asyncio loop from My Day's (a bug here cannot stop a reminder): reclaim -> materialize (every 2 min; step 1 reads only cheap per-learner settings and keeps learners near a slot, step 2 loads facts in bulk for just those) -> claim (`FOR UPDATE SKIP LOCKED`) -> deliver (decide in a short transaction -> push with NO lock held -> record) with backoff 30 s / 2 min then `push_failed` (never endless); 404/410 prunes the subscription |
| API (`/notify/*`) | `GET/PATCH /prefs` (also `hide_details`, written to `pl_prefs`), `GET /push/key`, `POST/DELETE /push/subscribe` (the same `plsvc.subscribe_push`: one device list - and this feature never depends on My Day's switch), `POST /open` (tap beacon; a foreign id is a silent no-op), `POST /ack` (the phone's receipt, NO login: a signed single-purpose 24 h token in the payload, `notify/tokens.py`, own key purpose so a My Day action token cannot be replayed here; 60 / min / IP), `POST /test` (one every 3 min), `GET /export`, `POST /delete-all` (data rights, answered while the switch is off) |
| Switch | `settings.notifications` = off (default) / owner (+ early access) / on, dashboard -> Access -> "Notifications" (`/admin/overview.notifications` + `notify_health`: sent / accepted / arrived / opened / cancelled / failed in 24 h, devices); `/me.notifications` |
| Client (`backend/test_client.html`) | the `NT` module after `PL`: a settings **sheet** (More -> Notifications; no route, no new screen), a Home **soft prompt** (only after the first practice - never on first launch - and not again for 14 days after "Not now"), `?n=<id>` tap beacon + the service worker's `nt-open` message. DOM-builder only (no innerHTML). Words in Hindi + English |
| Service worker (`sw.js` `dusu-v32`) | `push`: an NT payload (has `data.nid`) sends the receipt and does not post `pl-due`; `notificationclick`: `data.nid` opens Home and reports the tap. My Day's paths are untouched |
| Android (`android-twa`) | manifest: `DelegationService` + `SMALL_ICON` + `USE_HIGH_PRI_NOTIFICATIONS`, `FocusActivity`, `NotificationPermissionRequestActivity`; new monochrome `ic_notification_icon` (`gen_icons.py --notif-only`: white D-mark silhouette); the 4-hour alarm, `ReminderReceiver`, `BootReceiver`, the boot permission, the launch-time permission prompt and the `notif_messages` strings are GONE (`MainActivity.cancelLegacyReminders()` cancels the alarm and deletes the `dusu_reminders` channel an old install may still have); `versionCode 2` / `versionName 1.1`. `TwaLauncher.launch()` (what `MainActivity` uses) stores the delegation token `DelegationService` reads - verified in the library source |
| Data rights | `db.delete_user` + `admin_wipe_users` call `notify.service.delete_rows`; `privacy.html` and `account-deletion.html` say push addresses and notification history are stored and deleted with the account |

**The browser bar (X + URL) in a Play-installed app is the same root cause that blocks delegation:** the live `assetlinks.json` lists ONLY the upload key (`EF:02:68:...:62:0D`); Play re-signs the app with its own key, so Chrome cannot verify the link and falls back to a Custom Tab. Fix = owner dashboard -> **Android app link** -> add Play Console -> *Setup -> App signing* -> "App signing key certificate" SHA-256 -> **Check with Google** -> reinstall from Play (Chrome caches the verdict). Nobody but the owner can read that fingerprint.

**Gotchas:** `profile.practice_time` is MINUTES per day, not a time of day - hence `nudge_time`. "Practised today" is `progress.last_active == today (IST)`, which only advances for a *qualifying* session (the streak rule). `progress.streak_days` is only reset by the next activity, so a lapsed streak keeps its old number: alive only if last active today / yesterday. A new `nt_*` column on an existing table needs an explicit `ALTER` in `init_db`. The planning pass and the send both check the rollout switch, the blocked flag and the learner's own switch (two layers on purpose; the tests disable one to prove the other). The Android notification channel is made by Chrome per site, so `USE_HIGH_PRI_NOTIFICATIONS` applies to every delegated notification (My Day reminders and these). `bash ./gradlew` (the wrapper is not executable); on this Linux box Android Studio's JBR 21 builds it - no JDK 17 needed - with `local.properties` `sdk.dir=/home/vibhanshu/Android/Sdk` (git-ignored).

**Verified (2026-10-20, scratch infrastructure only):** `tests/notify/` (see its README: `run.sh`, `mutants.sh`, `browser/run_real.sh`, `browser/oldnew.spec.cjs`): unit **189**; scratch Postgres through the real HTTP layer + the real engine on a fake clock **158** (old -> new schema rehearsal, gates, validation, who-gets-what on a Wednesday, planning twice / by eight workers makes one row, the send-time re-check, both languages, lock-screen privacy, the ignore-three back-off, a late server, the weekly note and its ISO-week key, dead / failing push services, receipts and taps, the test button, isolation between learners, the rollout switch + the loop itself, data rights); **21 planted bugs, all caught** (four first survived - two layers guarding one thing - and were closed with tests that disable the other layer); real Chromium against the real app + scratch Postgres **109** (a fake push subscription is the only fake: the prompt, turning on with a real subscription reaching the server, the three reminders, the time, the lock-screen switch, the test button, turning off, blocked / unsupported states, Hindi, the tap beacon, the rollout switch, the owner dashboard select (no other switch changes), dialog semantics + Tab trap, layout at 360 / 390 / 1280 - screenshots looked at); regression: My Day 92 + 293, Job Interview Practice 309 + 188, Grammar Coach 88 + 18 + units unchanged; old = old with the switch off: visible text and element order identical on all 15 screens, the DOM diff is only the new hidden `nt*` markup (the pixel tier is noisy - the OLD page compared with itself differs on a random screen). `./gradlew assembleDebug` builds; the merged manifest has the delegation service, no boot receiver / permission, `targetSdk 36`. **Not verified (a physical phone is the only proof):** real delivery on Android (delegated Web Push, the Android 13 permission dialog, tap -> opens inside the app with no URL bar, battery killers on Xiaomi / Oppo / Vivo), Chrome's cached app-link verdict, Hindi wording by a native speaker, and that a signed release AAB installs from Play with the new fingerprint listed.

**To turn it on:** owner dashboard -> Access -> Notifications -> Owner + early access, install the new build on your phone, More -> Notifications -> Turn on, **Send me a test notification** with the app closed and the screen off, then watch the dashboard's accepted / arrived / opened counts, then Everyone.

**Update 2026-10-27 - why "notifications do not work" for people who install the web app, and what was fixed (built 2026-10-27, DEPLOYED 2026-10-28 with sections 19 and 20; the `notifications` switch stays OFF until the owner has proven one on a phone).** Measured: switch Off, 0 push devices, no VAPID row, no `/notify/*` request in 7 days of logs - nobody had ever turned them on - plus these silent failure points in the code: the service worker awaited the "arrived" receipt BEFORE showing the notification (a slow or failing receipt = no notification); a visible app showed nothing at all; a nudge time in 22:00-23:59 had no slot (quiet hours) and said nothing; `pstate()` trusted the browser's permission only (a server that lost the device, or a changed VAPID key, was never noticed); the badge was the 1.7 MB logo; the iPhone wording was wrong (push exists only from an app added to the Home Screen). Fixed: `sw.js` v33 **shows first, receipt after** (independent: a failed show still sends the receipt, a failed receipt never blocks the show); while a DuSu window is VISIBLE the system notification is raised silent (iPhone requires one per push) and the window is told (`nt-nudge`) to draw its own in-app notice; the 192 px icon + a monochrome 96 px badge; `GET /notify/prefs?endpoint=` answers `this_device` (does the server hold THIS phone?) so the client resubscribes when it does not, or when the stored key differs from `/notify/push/key`; a quiet-hours warning when the chosen time falls inside them; iPhone wording ("Add to Home Screen first"); a **primer after install** (first standalone launch / `appinstalled`) that asks once (`dusu_nt_prime`); the test button's lifecycle (`POST /notify/test` -> `GET /notify/test/{id}`: queued -> accepted by the push service -> reached this phone -> opened, a 60 s timeout listing likely causes - battery saver, OEM autostart). Still unproven on a real phone; nothing is promised until the owner runs the test notification on the handset (installed web app AND the sideloaded APK).

---

## 19. Keys - per-key health, a usage ledger, and pop-ups that say what happened (built 2026-10-27, DEPLOYED DARK 2026-10-28 - plan in `~/.claude/plans/velvety-wishing-corbato.md`; harness `tests/keys/`, README inside)

**Why.** Measured before the change: every failure reached the learner as one of three generic messages; ~25 sites in `main.py` decided with substring tests and six classifiers disagreed (`"rate"` matches `"generate"`); `_is_quota` read only the LAST error; `detail:"quota"` also means DuSu's OWN plan cap, not only a key limit. The cooldown map was keyed by provider NAME for the whole process, so one learner's 429 made everyone skip that provider (90 s - 30 min; 6 h for "dead") and switched Grammar Coach off for all. A bad key never reached it - Groq 401, **Gemini 400 "Please pass a valid API key"** and OpenRouter 401 all missed the gate - so a dead key was retried on every call (the server's own Groq key, dead since 2026-10-06, wasted two requests per call). Nothing was metered (`usage_daily` had 0 rows). `/keys/verify` was destructive (replace-all: empty boxes wiped the stored set, one good key dropped the rest, a 429 counted as verified, only the provider's first model was probed so a retired model read as "bad key"), and `resolve_keys` let a browser-sent key beat the stored one, so a key replaced on phone A looked "invalid" on phone B. The Keys page filled from `localStorage` only - it looked empty on another phone or after a cache clear - and its messages sent people to a "Settings" screen that does not exist (the real path is More -> DuSu keys).

**Rules of the road.** Two verified keys to start (unchanged); at run time ONE working key keeps DuSu going; when every key is down the learner gets a pop-up with the exact reason per provider and the soonest reset - never a silent fallback to DuSu's own keys. **Only positive evidence marks a key invalid** (a 401 on any provider, a Gemini 400 that says the key is not valid, a 403 that says leaked / disabled); a timeout, a 5xx, a 404 (a model the platform retired) or text we cannot read is never evidence about the key.

| Piece | Where |
|---|---|
| Package (shape of `notify/`) | `backend/app/keys/`: `classify.py` (PURE; typed SDK errors `.status_code` / `.body` / `.response.headers`; Groq dict, Gemini LIST and OpenRouter nested bodies; "Limit / Used / try again in", `retry-after`; limit scope minute / day / upstream; the provider's published daily reset is marked `approx`), `gate.py` (per-key circuit breaker keyed `(provider, fingerprint)`, fingerprint = HMAC(server secret, provider\|key)[:12]; limited until the provider's own `retry-after`, else the legacy 90 s / 30 min; invalid until re-added / re-checked / 6 h; forbidden 5 min; ONE single-flight half-open probe so 20 concurrent callers cannot hammer a limited key, one early probe per chain per minute, bounded map), `errors.py` (`ProviderChainError(RuntimeError)`: the SAME message text as before + `.state` no_keys / all_invalid / all_limited / transient + `.kp()`), `ledger.py`, `probe.py` (zero-quota auth probes - Groq `/models`, Gemini `/models`, OpenRouter `/key` - the one-call chat check, and the server chain's own health, cached 10 min), `service.py`, `api.py`, `models.py` |
| The walker | `providers/openrouter_provider.py`: `_complete` dispatches on `set_active_keys(keys, uid=, engine=)` - `engine` False = **`_complete_legacy`, today's walker verbatim** (global cooldown map and all); True = `_complete_v2` (per key: an invalid / limited key is skipped without a request; a timeout, connection error, 401 or 403 leaves the provider instead of trying its next model; fail-fast when every key is gated). An AST test fails the build if any `set_active_keys(...)` call forgets `uid=` or `engine=` (12 sites). Tests inject fake providers through `_http_client_factory` (an `httpx.MockTransport`) - only tests set it |
| Tables (both NEW, no ALTER) | `kh_status` (learner x provider x fingerprint: status ok / limited / invalid / forbidden / unknown, `kind`, `scope`, `since`, `reset_at` + `evidence` / `approx`, `expired`, last ok / error, `rl_*` = the provider's own allowance, `meta`) and `kh_usage` (learner x PROVIDER quota day x provider x fingerprint: `requests`, `ok`, `limited`, `invalid`, `other`, tokens). The quota day is UTC (Pacific for Gemini) so "used today" lines up with "left today". No key text anywhere |
| Ledger | every attempt that reached a provider is counted **at dispatch** (a cancelled attempt still counts - the provider received it) and settled in `finally`; an in-memory aggregator flushed every 5 s and on shutdown, ONE ROW PER TRANSACTION (a row that cannot be written - a learner deleted a moment ago - is dropped and counted, never poisons the batch); one uvicorn worker keeps the in-memory totals exact; pruned after 90 days. Server-chain calls are counted too (for the owner and later plans); the learner's card shows only their own keys |
| What "left" means | Groq reports daily allowance headers -> **exact**; OpenRouter -> **computed** (`OPENROUTER_FREE_DAILY` 50 / `OPENROUTER_PAID_DAILY` 1000 minus DuSu's count, shown "about"); **Gemini has no quota API** -> "used today" plus an honest "Google doesn't report your remaining quota - DuSu tells you the moment it is reached". No invented numbers, and no "resets at ..." without provider evidence |
| Stored keys win | `resolve_keys` (engine on): per provider the stored key wins and a browser-sent key only fills a provider with nothing stored; saves **merge** per key under `SELECT ... FOR UPDATE` (12 concurrent saves lose nothing; an empty save wipes nothing); the browser only ever sees masked values. GitHub Models is dropped from the chain, `providers_from` and `has_user_keys(strict)` (it answers `200 "OK"` to ANY token - it can neither validate nor serve) |
| API | `GET /keys/status` (masked value, status, since, reset + `now`, used today, allowance `{exact\|computed\|unknown}`), `POST /keys/save {provider, key}` (verifies ONLY that key: a cheap auth probe, then one chat call), `POST /keys/remove`, `POST /keys/recheck` (4 / min / learner; header auth only - never `?key=` or `str(exc)`, httpx messages embed the URL), `GET /keys/export`. All answer 404 while `key_health` is off for the account. Legacy `/keys/verify` = merge (old clients still work; `saved` is computed from the merged set); `/keys/get` stays only for the phone-side Groq Whisper key |
| Wire (additive only, section 17's precedent) | a `kp` field `{state, keys:[{provider, kind, scope?, reset_at?, approx?, expired?}], now}` on the EXISTING `quota` / `error` / `home_error` / `translate_error` / `practice_error` frames and on HTTP 402 / 429 bodies (`KeyProblem(HTTPException)` + one handler); `detail` strings unchanged. `main.key_failure(e)` replaces the ~25 `_is_quota` blocks, keeps the string fallback for a plain `RuntimeError("all providers/models unavailable ... 429")` and walks `__cause__`. The pop-up opens only when the SERVER authored `kp` - never from a bare `quota` (that can be DuSu's own plan cap). `/me.keys` = `{stored, working, limited, invalid, unknown, state, used_today, next_reset_at, min}` (counts only, never key text) |
| Switches | `settings.key_health` (engine + `/keys/*` + stored-first + ledger, per learner) and `settings.keys_ui` (the screens; they also need the engine) = off (default) / owner (+ early access) / on; dashboard -> Access -> "Key health (per-key engine)" / "Key screens"; `/me.key_health`, `/me.keys_ui`. The dashboard also shows DuSu's OWN key health (a cached zero-quota probe, a dead server key is flagged) and `/health` carries `server_keys` from that cache - it never probes on the request path |
| Client (`test_client.html`) | `KY` module: the Keys screen is drawn from `/keys/status` on every open (never from `localStorage` alone; it repaints when the data arrives; a non-JSON answer = feature off): masked value, status chip, used today / left, **Change / Test / Remove**, per-block "Save key", "Check all keys", "2 of 3 working - you need 2 to start", "never share your key"; the Home card `#kyCard` ("Your AI keys - 3 working - 38 requests today", per-key chips); the pop-up `#kySheet` (`KY.problem(kp)` is called from every existing site - WS frames, the HTTP 402 / 429 handlers through a fetch wrapper, the Practice / Interview / Grammar error maps; plain words per key, the soonest reset in the learner's zone, Fix my keys / See plans / Later; deduped by a state signature + 10 min; opens once on Home load when `/me.keys.state` changed since last seen - `dusu_ky_seen`). `ARB` decides which ONE Home prompt shows: key problem > install > notifications > WhatsApp (14-day snooze each). The pop-up and card are bilingual (Hindi default, follows the learner's choice); the Keys screen itself stays English (section 11) |
| Data rights | `keys.service.delete_rows` in BOTH `db.delete_user` and `db.admin_wipe_users` (child-first `KY_TABLES`), the ledger forgets a deleted learner, `GET /keys/export`, `privacy.html` + `account-deletion.html` say key health and usage counts are stored and deleted with the account |
| Shared-code edits (each reviewed) | `main.py` (`resolve_keys`, the 12 `set_active_keys` sites, `/me`, `/health`, admin, `/keys/verify` merge, startup / shutdown hooks), `config.py` (GitHub dropped), `db.py` (`has_user_keys(strict)`, delete hooks), `grammar/budget.py` ("cooling" = a *limited* key in the learner's OWN chain, invalid excluded; `B.cooling` stays zero-arg, `_ask` kwargs unchanged), `grammar/api.py`, `resume_interview/api.py`, `practice.py`, `practice_talk.py`. `_mark_cooldown`, `_cooldown`, `cooling_down()` are untouched (Resume Interview's unit tests pin them) |

**The one part that runs with every switch OFF:** the keys loop (`keys_ledger.run_forever`, started from the app's `startup` hook next to My Day's and Notifications' loops) flushes the ledger and, every 10 minutes, sends one zero-quota auth probe per key of DuSu's OWN chain (Groq `/models`, Gemini `/models`, OpenRouter `/key` - no chat, no quota) to fill the owner dashboard's "DuSu's own keys" line and `/health.server_keys`. Everything else (walker, precedence, `/keys/*`, `kp`, the screens) is per-learner behind `key_health` / `keys_ui`.

**Gotchas:** the gate and the ledger live in memory - one uvicorn worker is the deployment (a second worker would double-count and gate per process); a restart forgets the gates and the first call re-learns a dead key with ONE wasted request; `_cooldown` stays process-global for the SERVER chain and the legacy path; a `kh_*` column added later needs an explicit `ALTER` in `init_db` (`create_all` adds tables only) - anything that may evolve belongs in `meta`; `set_active_keys` without `uid=` is refused in the engine path (one forgotten site would silently run a learner on the wrong chain - hence the AST guard); `kp` never carries provider error text or key text (the tests grep for both); Groq's "Limit ... Used ... try again in 1m3.5s" text is parsed, but a day limit phrased any other way falls back to the published reset marked `approx`; the free-tier limits change without notice and Google exposes no Gemini quota endpoint; the synthetic error bodies in `tests/keys/world.py` are guesses of what the providers say - `tests/keys/capture_real_errors.py` (owner-run, keys from the environment, never printed) records the real ones so they can be checked.

**Test harness notes (`tests/keys/`):** scratch Postgres on a `docker network create --internal` network (no route to the internet, so a bug cannot spend a real key); every provider is a scripted fake. A concurrent test only interleaves if the fake takes time (`R(200, ..., delay=0.15)`); the re-check endpoint allows 4 a minute and saving 8, so a browser spec that clicks Test more often must use another learner; a learner whose keys an earlier section left rejected gets the pop-up on Home load (rightly) - use a fresh learner; the new features default to Hindi, so specs set `POST /lang` first. "Old = old" is measured against `057e58c` (the last commit before this work): `git show 057e58c:backend/app/providers/openrouter_provider.py > tests/keys/.head/provider_head.py` and `git show 057e58c:backend/test_client.html > tests/keys/.orig.html`.

---

## 20. Install app + a WhatsApp group (built 2026-10-27, DEPLOYED DARK 2026-10-28 - switch `install_mode`)

**Why.** The Play app is not published yet; DuSu had no install code (the manifest pointed 192 / 512 / "maskable" at ONE 1254 px, 1.7 MB `logo.png`, had no `id`, and the `apple-touch-icon` was the same file); and there was no channel for "this is new / the Play app is live / I have a problem". Research result on "can a person who taps Install be auto-enrolled as a Play tester?": **no** - Play enrols testers only through an email list or a Google Group, the person must still open the opt-in link and accept it, and no API enrols anyone. So the install here is the **web app** (PWA), and the WhatsApp group carries the "the Play app is live, here is the opt-in link" announcement later.

| Piece | Where |
|---|---|
| Manifest + icons | `manifest.webmanifest`: `id: "/"` (today's identity - changing it re-identifies existing installs), `start_url` stays `/`, real 192 / 512 / maskable-512 icons (`android-twa/gen_web_icons.py`, from `icon-master.png` over `#070a14`) with VERSIONED names in `backend/assets/icons/` (`dusu-192-v1.png`, `dusu-512-v1.png`, `dusu-maskable-512-v1.png`, opaque `apple-touch-180-v1.png`, monochrome `badge-96-v1.png`; served by the existing `/assets` mount and cache-first, so a changed icon needs a NEW file name), `related_applications` (the Play app) + `prefer_related_applications: false`. The `<head>` points at the small icons, no longer at the 1.7 MB logo. `sw.js` `dusu-v33` |
| Install module | `INST` in `test_client.html`: `beforeinstallprompt` is captured by an early `<head>` script (only when `dusu_inst_on === "1"`, written from `/me.install_mode` - with the switch off the browser keeps its own bar and nothing is intercepted). Modes: **prompt** (Chrome / Edge on Android and desktop: one tap -> the real `prompt()`), **ios** (Safari: the 3 Add-to-Home-Screen steps), **inapp** (WhatsApp / Facebook / Instagram browsers: "Open in Chrome" + copy link), **menu** (Firefox / Samsung / the event never fired: the browser-menu path), **installed** (standalone `display-mode`, `navigator.standalone`, `getInstalledRelatedApps()`, the TWA flag `dusu_twa` -> nothing is drawn). Placements: a Home header pill, a More row, and a one-time sheet from the 2nd visit (`dusu_inst_visits`, 14-day snooze `dusu_inst_snooze`); it only asks after the level check (`onboarded`) and re-checks at the moment it fires that no other modal or higher-priority prompt is open. `appinstalled` opens a success sheet that leads into the notification primer (section 18) |
| WhatsApp group | `CM` module: the invite lives in the **settings table** (`whatsapp_group`, edited on the owner dashboard next to the switch, validated as `https://chat.whatsapp.com/<code>` or `https://whatsapp.com/channel/<code>`, every tracking parameter stripped) - **not in this public repo** (scrapers harvest invite links). `/me.community = {whatsapp}` only while `install_mode` is on for the account. Placements: a Home card (`ARB`: after key problems / install / notifications; 14-day snooze `dusu_cm_asked`), a More row, Help & Feedback, the install sheet's success step. One honest line - members see each other's numbers (recommended: admins-only posting + join approval in WhatsApp, or a Channel, which hides numbers). **Never in the key pop-up** (a learner could paste a key there); the Keys page and the join sheet say "never share your key" |
| Switch | `settings.install_mode` = off (default) / owner (+ early access) / on, dashboard -> Access -> "Install app + WhatsApp group"; `/me.install_mode`, `/me.community`; `POST /admin/settings {install_mode, whatsapp_group}` |

**Gotchas:** Chrome fires `beforeinstallprompt` at most once per page load and only when the page is installable (valid manifest, a service worker with a fetch handler, https or localhost) - the browser spec asserts `Page.getInstallabilityErrors` is empty; iPhone has no such event (the 3 steps are the only way, and push works only from the Home-Screen app); a TWA is never prompted; never change the manifest `id`; the Play App Signing fingerprint (dashboard -> Android app link) is still the owner's step and is what removes the browser bar inside the Play app.

**Verified (2026-10-27 / 28, scratch infrastructure only; sections 18, 19 and 20 together):** `tests/keys/`: unit **172**; parity ("old = old": today's walker replayed, `.head/provider_head.py` from `057e58c`) **49**; scratch Postgres through the real HTTP layer + the real walker **155**; the real `/ws/interview` handler in every model-using mode **71**; real Chromium against the real app **168** (`keys.spec.cjs`) + **111** (`install.spec.cjs`, incl. no installability errors from CDP); service worker in a Node `vm` **33**; static hygiene of the new client modules **92**; client old = old with the switches off **28** (text, element order and static DOM identical; the pixel tier tolerates the two screens the ORIGINAL page already differs from itself on); **44 server + 8 client planted-bug mutants, all caught** (client mutant C3, "a stale answer overwrites a newer one", SURVIVED the first run - the spec had no out-of-order test; one was added, and writing it exposed a race in the test itself: it must wait until the page has APPLIED the newer answer before releasing the held older one). Regression, unchanged: Job Interview Practice unit 309 + selftest 188 + browser 90; My Day unit 92 + selftest 293 + browser 122 + 137; Notifications unit 189 + selftest 158 + browser 109; Grammar Coach selftest 88 + WS harness 18 + browser 40. **One pre-existing failure, not from this work:** Job Interview Practice's `parity_server.py` check "existing registry entries are unchanged" (86 / 87) fails identically on the committed `057e58c` - Grammar Coach added a `home_content` registry entry after that parity baseline. The built image was tested AS BUILT (files sha256-identical to the tested tree, `import app.main` clean, the keys tiers + browser specs + Notifications / My Day / Grammar Coach suites against the code baked into `dusu-backend:latest`). **Not verified (only a real phone / the real providers can):** the real 429 / 401 bodies and headers of Groq, Gemini and OpenRouter (the fixtures in `tests/keys/world.py` are synthetic; run `tests/keys/capture_real_errors.py` with your own keys to record the real ones), Web Push delivery and the install flow on a physical phone (Chrome Android, iPhone Safari, the Play TWA), Hindi wording by a native speaker, Gemini's real free-tier limits (no quota API).

**Deployed 2026-10-28 (dark)** - commit `305dfaf` (local, not pushed), image `dusu-backend:latest` = `9bfe6140d134`, `sw.js` = `dusu-v33`. Same procedure as section 14: **rollback image** `dusu-backend:pre-keys-install` (= the previous production image `be8d2032e0f9`; `docker tag dusu-backend:pre-keys-install dusu-backend:latest && docker compose up -d --no-deps backend`; the two empty `kh_*` tables and the `whatsapp_group` setting are harmless to leave), pre-deploy dump `~/dusu-backups/dusu-before-keys-install-20261027-235623.sql.gz`. **Live check:** clean start, `init_db()` created `kh_status` + `kh_usage` (0 rows), every other row count and every rollout switch identical before / after (19 users, 15 stored key rows, 74 conversations ...), none of `key_health` / `keys_ui` / `install_mode` / `notifications` has a settings row (= off for everyone), `sw.js` v33, the new page, the manifest `id` and the new icons on `localhost:3878`, `dusu.ranabrothers.online` and `dusu.ruralrootcloud.com`, `/keys/status` answers 401 without a login on all three. The checks wrote nothing to production except the one deliberate row: the WhatsApp invite in `settings.whatsapp_group` (learners cannot see it until `install_mode` is on). **`/health.server_keys` after the deploy: Groq `invalid` (DuSu's OWN Groq key, dead since 2026-10-06 - replace it in `backend/.env` and restart), Gemini `ok`, OpenRouter `ok`.**

**To turn it on (owner dashboard -> Access), in this order:** 1. "Key health (per-key engine)" -> Owner + early access; dogfood with a typo'd key and a limited key (the owner rides the server keys: use an early-access tester account for the BYOK path); 2. "Key screens"; 3. "Install app + WhatsApp group" (check the link on the dashboard first - the group should be admins-only posting with join approval, or a Channel); 4. "Notifications" only after a test notification reached a real phone; then each to Everyone. Rollback of any one = set it back to Off (live within ~60 s). Also still the owner's: the Play App Signing fingerprint (dashboard -> Android app link -> Check with Google), the AAB upload, and the real-phone checks.

**Update 2026-10-28 (evening) - the key pop-up and the Keys screen redrawn; DEPLOYED, and `key_health` + `keys_ui` SWITCHED ON FOR EVERYONE (2026-10-28, 16:26 and 16:28 IST, at the owner's request, without a real-phone run first - rollback: set both to Off in the dashboard, live within ~60 s).** The owner's report: "the key not working / expired / limit hit pop-up is not good, it should be nice". Measured first: the pop-up was a title, a few lines of text in boxes and three buttons (screenshots of every state were looked at), and in production it was not even shown - `settings` had no `key_health` / `keys_ui` row, so every learner got the OLD toast ("Your keys hit their limit...") and the old Keys page (that is why the owner could still see the "not good" message after the Keys work had been deployed). What changed (`KY.paintSheet`, `backend/test_client.html`; DOM-builder only, no `innerHTML`; both languages):

| Piece | What |
|---|---|
| Hero | a tinted card: a clock (amber) for a limit, a key (red) for a rejected / expired / blocked key, an indigo key for "add your keys"; the title says what happened and ONE plain sentence under it says what to expect - for a limit **when it should be back** ("It should be back in about 7 min. Your chats are safe."), for a rejected key "Replace it and you're back in a minute", for one key down "DuSu keeps going on your other key" |
| A card per key | provider avatar, name, a coloured status chip (Daily limit reached / Too many requests / Rejected / Expired / Blocked / Out of credit) and one line of detail ("Comes back in about 7 min", "Should come back tomorrow at 6:24 AM", "This key has expired. Tap Replace to add a new one."); a rejected / expired / blocked key also has a **Replace** button (`fixKey(p)`) that opens THAT provider's box on the Keys screen, focused |
| Next step | **Fix my keys** is the one large button (with exactly one rejected key and no limits it goes straight to that key's box); See plans (only when a limit is involved) and Later sit under it. A mixed state (one key rejected, one at its limit) is headlined "Your AI keys need attention", not "limit used up" |
| Keys screen | each key's block is a card tinted by its state (green / amber / red) |
| Unchanged | the engine, `kp`, the dedupe, the Tab trap, focus, Escape, the Home card, the rules about WhatsApp / "Settings" never appearing in it; `sw.js` `dusu-v36` |

**Verified (2026-10-28, scratch infrastructure only):** `keys.spec.cjs` **180** (was 168: the pop-up assertions follow the new structure, plus "Replace opens the right box"), install 111, static hygiene 92, service worker 33, `popup-look.cjs` **39** (every state - limited, rejected + expired, mixed, one key down, no keys, blocked / no credit - at 360 / 390 / 1280 px, English and Hindi: it fits, nothing overflows, every control >= 40 x 40; the screenshots in `~/.cache/dusu-ky-shots/look-*.png` were looked at), Face-to-Face / Interview / practice / Home chat 343, Daily / Learn 166, Grammar 40, Notifications 109; "old = old" 26 / 28 (nothing was added to the markup - the two failing checks assert "something was added"); the same keys suites pass against the code baked into the built image. **Deployed** - commit `557f887` (local, not pushed), image `fcb3783d58e1`, rollback image `dusu-backend:pre-key-popup` (= `ced87a7f8759`), dump `~/dusu-backups/dusu-before-key-popup-20261028-162311.sql.gz`; every row count and every switch identical before / after; `sw.js` v36 and the new code on all three addresses. **Switched on:** `key_health` first (checked: 0 log errors, `/health` fine, the app's own `key_health_enabled()` true for an ordinary learner), 2 minutes later `keys_ui` - by `INSERT ... ON CONFLICT` into `settings` (the app reads settings with a ~60 s cache). `install_mode` and `notifications` are still off. Watch the first days: `/admin/overview` -> the keys health block, and the server log for `[keys]` lines. Not verified: how it looks on a real handset, the real providers' own 429 / 401 wording (`tests/keys/capture_real_errors.py`, with your own keys), and the Hindi wording by a native speaker.

**Update 2026-10-28 (later) - "free version / free keys" said plainly, a plan card, and EVERY limit is the bottom pop-up (DEPLOYED, live for everyone).** The owner: "in the pop-up make it clear: free version and free keys, so the learner knows they are on the free version and better to go with a subscription for better practice - and right now a small banner shows at the top, not a pop-up at the bottom". Measured: the key pop-up covered only what the server named in a `kp`; three other paths still raised the small top notice - the WebSocket `quota_exceeded` frame (the free daily limit / the finished trial: toast AND a forced jump to the plans page), the two HTTP 429 handlers of the lesson / level-test calls (a toast in ADDITION to the pop-up), and the client's "N sessions a day" check before a chat starts (`overLimit()` -> `limitNote()` x5). What changed (`KY` + `limitNote()` / `limitPopup()` in `backend/test_client.html`):

| Piece | What |
|---|---|
| The message | every key pop-up carries a tag "FREE VERSION . FREE KEYS", one sentence ("You're using DuSu's free version with free AI keys. Free keys have daily limits and can stop working without warning.") and a **plan card** ("Better practice with a DuSu plan - more practice every day, and no keys to find, paste or fix."). No price in the pop-up (the plans page owns the prices) and no "subscribe now": see the caveat below |
| Buttons | a limit with a healthy key: **See plans** first, then My keys, then Later; a rejected / expired / blocked / missing key: **Fix my keys** first, then See plans, then Later. The button row is `position: sticky` at the bottom of the sheet, so the main action is on screen even with three key cards on a 360 x 740 phone |
| The free version's own limits | `KY.plan(kind, {limit})`: `daily` (a `quota_exceeded` frame: "You've used today's free practice - The free version allows N turns a day. It starts again tomorrow."), `trial` (`trial_over`: "Your free trial has ended - Choose a plan to keep practising with DuSu."), `sessions` (the client's daily session cap: "... (N sessions) ..."). Tag "FREE VERSION", no key rows, See plans / Later; Later on a refused chat goes Home (the chat cannot go on). The learner is no longer thrown onto the plans page |
| An unnamed limit | `KY.generic()`: a `quota` frame or an HTTP 429 whose body has no `kp` (`limitPopup()` reads the body first, so a body WITH `kp` is not painted twice): "Your free AI limit is used up for now", the note, the plan card, See plans / My keys / Later |
| Always shown | `plan()` / `generic()` bypass the 10-minute "already told" dedupe (that is for a key problem the learner can do nothing about; here the learner has just tried something and was refused - a silent no-op would look like a dead button) |
| Fallback | all of them return `false` while the key screens are off, and the caller then keeps the old top notice / plans page exactly as before |

**Caveat the owner must know:** the plans page (`/subscribe`: Starter 299 / Plus 599 / Pro 899 per month) has NO payment behind it - choosing a plan and tapping Proceed only prints "payment coming soon (work in progress)". "See plans" is therefore a dead end for anyone who wants to pay today; the copy was kept honest (it names a plan, never "subscribe now" / a price). Building the payment is a separate project.

**Verified (2026-10-28, scratch infrastructure only):** `keys.spec.cjs` **207** (new: each limit kind, no banner, no forced navigation, generic, Hindi, the screens-off fallback), `popup-look.cjs` **83** (every state - limit, rejected, expired, mixed, one key down, no keys, blocked, plan daily / trial / sessions, generic - at 360 / 390 / 1280, English + Hindi: fits, nothing overflows, controls >= 40 x 40, the main button on screen without scrolling; the screenshots were looked at), install 111, static 92, sw 33, Face-to-Face / Interview / practice / Home chat 343, Daily / Learn 166, Grammar 40, Notifications 109; "old = old" 26 / 28 (markup untouched); the keys, install, look and voice suites also pass against the code baked into the built image. One Daily scenario (F1, a click on `#dailyFinish`) timed out once in a long sequential run and passed on the immediate re-run alone and in the full spec - not explained, noted. **Deployed** - commit `a4f7729` (local, not pushed), image `be34b9942d1f`, `sw.js` `dusu-v37`, rollback image `dusu-backend:pre-plan-popup` (= `fcb3783d58e1`), dump `~/dusu-backups/dusu-before-plan-popup-20261028-171634.sql.gz`; every row count and every switch identical; live checks on all three addresses incl. a real WebSocket ping -> pong. Not verified: a real handset, the Hindi wording by a native speaker.

---

## 21. A locked screen pauses every voice chat (fixed 2026-10-28 - Daily Talk / Learn first, then Face-to-Face / Interview / practice / Home chat - harness `tests/daily_voice/`, README inside)

**The bug (a tester's report).** Daily -> Chat with DuSu: lock the phone mid-session, unlock - the Speak mic and Reply are dead until the chat is ended. **Cause, read from the code:** the one global `visibilitychange` handler ran `stopAllVoice()` on "hidden": `running = false`, the recogniser dropped with its `onend` removed, speech cancelled, **the socket closed and set to `null`**. Nothing handled the screen coming back, and every way to continue was gated on what that destroyed: `startDailyListen()` / `startHindiListen()` begin with `if(!running) return;` (so the mic button and Reply did nothing, silently), `#dailyMic` was left `disabled` (its re-enables were the nulled `onend` and the reply chain that `speakEpoch++` aborted), and with `ws === null` even a working mic could send nothing - Finish found "ws not open" and the result screen showed nothing. Learn had the identical defect. A second dead-mic path with the same symptom: after a `quota` frame the client sets `running = false` but the socket stays open, so the mic stayed dead after the pop-up was dismissed.

| Piece | Where |
|---|---|
| `VP` (pause / resume) | `backend/test_client.html`, after the Daily block. The `visibilitychange` handler: hidden -> `VP.owns() ? VP.pause() : stopAllVoice()`, visible -> `VP.resume()`. `owns()` = the Daily screen in Daily mode, or the Learn screen in Learn mode - **nothing else** (Face-to-Face / Interview / the Home chat keep the old kill-on-hide). `pause()` silences the mic and the voice (bump `speakEpoch`, stop `drec` / `lrec`, cancel speech) but keeps `running`, the socket, the turns and the pending line. `resume()` cancels stale speech, asks whether the socket is alive (an open one after a lock of 20 s or more gets a `ping` and must `pong` within 3 s - a half-open socket still LOOKS open), then restores the screen by state (`dailyRestoreUI` / `learnRestoreUI`: the mic is handed back unless the opener or an answer is still on its way) or reconnects quietly. Away longer than 10 minutes the page closes the socket itself (the server saves the chat on close, as it always did) and `resume()` reconnects |
| Hidden-aware speech | `greetDaily`, `handleDailyTurn`, `greetLearn`, `handleTranslation` render everything but do not SPEAK while `document.hidden` (a reply landing on a locked phone is shown, not spoken). `say()` itself is untouched (the level test uses it) |
| Quiet reconnect | `dailyConnect(quiet)` / `learnConnect(quiet)` (the socket creation moved out of `startDaily` / `startLearning`; with `quiet=false` the `start` frame is byte-identical to before - the new `reconnect` key is omitted, not `false`). `quiet` = not counted as a new session (`usageInc` is skipped), the old socket is detached and closed, the Daily `start` carries `reconnect: true` + the in-memory turns, a pending line (`dailyPendingMe` / `learnPending`) is re-sent once the server answers. A tap on the mic / Reply on a dead socket reconnects first (`dailyTap` / `learnTap`; a live socket takes exactly the old path, synchronously - a mic must start inside the tap on iPhone) and forces `running = true` for an open socket (the quota case). **Reconnects happen only on unlock or on a tap - never in a loop** (a blocked account whose socket the server closes would otherwise reconnect forever) |
| Server (`backend/app/main.py`, additive) | WS loop: `ping` -> `pong`. Daily `start` with `reconnect` **exactly `true`** and a non-empty replay: the transcript is seeded as before, **`session.turns = 0`**, the server answers `daily_resumed` and makes **no model call** (no greeting). Anything else - no flag, `"true"`, `1`, an empty replay, another mode - is today's path unchanged. Learn needs no server change (a client flag keeps `greetLearn` silent). A rolled-back (old) server ignores the flag and opens with a greeting - safe |
| Words | `dReconn`, `dDropped` in the English and Hindi tables (shared by Daily and Learn). `sw.js` cache `dusu-v34` |

**Rewards are never paid twice.** The first part of a chat is saved and rewarded when its socket closes (as always). A quiet reconnect replays the last turns for context only (`turns = 0`): finishing straight away writes no XP, no summary row and sends no `speaker_progress`; one new turn afterwards is rewarded once (+20). (The pre-existing next-day resume, with no flag, still counts the replayed turns - pinned, not changed.) After `speaker_progress`, `ended` finding the result screen still spinning now renders the empty result at once instead of waiting 20 s.

**Gotchas:** `usageInc()` is a no-op for an "unlimited" learner (every e2e learner is) - a test must spy on the CALL, not read `dusu_usage` (the first version of the spec checked `dusu_usage` and a planted bug sailed through). `speechSynthesis.cancel()` ENDS the utterance in flight (an `error` event) so an awaited `say()` resolves and a chain carries on - `speakEpoch++` is what stops it; a speech stub whose `cancel()` never ends the utterance hides this. The speech watchdog in `say()` is `3500 + len * 90` ms. A reconnect test must wait for the first part's own end-of-session save (a model call) before measuring "no model call". `VP.pause()` must not clear itself from `ws.onclose` (a close that arrives while hidden is exactly the case `resume()` handles).

**The other chats (the second release, 2026-10-28).** The same defect and the same cause on the screens that share `#session` - Face-to-Face (Talk), Interview, a Practice Room conversation (viva / discussion / custom) and the Home chat: after a lock the mic never came back, End showed "wrapping up" forever and an interview in progress was lost. They are now paused and resumed exactly like Daily / Learn, and a socket that did not survive is replaced by a quiet reconnect, which needed a server resume of its own.

| Piece | Where |
|---|---|
| Pause / resume | `VP.owns()` also covers the session screen in `conversation` / `interview` / `practice` / `home`; `pause()` also stops the conversation recogniser (`stopListening()`), clears `aiSpeaking`, the faces and (Home) the "open the mic" timer; `sessBack()` pings after a lock of 20 s or more and then either `sessRestoreUI()` (the mic comes back - unless the opener, an answer or the report is still on its way: `_thinkNode` is the shared "something is coming" signal) or `sessRevive()`. The Home chat hands its own state back through `HM.pause()` / `HM.resume()` (a greeting the lock cut short counts as said; a typed first line that never left is sent) |
| Hidden-aware voice | `speak()` returns at once while hidden (the reply is on screen, not spoken); `startListening()` refuses while hidden - ONE central guard, so the reply loop and the Home chat's timer both end there; `delayedListen()` never starts a second recogniser (`!recog`) |
| Quiet reconnect | each start site keeps the `start` frame it sent (`sessFrame`); `sessRevive()` re-sends it with `reconnect: true`, `resume` (the last 60 lines read back from `#feed` - what the learner sees is what the server is told; an unanswered last learner line is NOT history), `elapsed`, a fresh `token` / `keys` / `hour`, no `seed` / `opening` / `plan`, and a NEW Grammar Coach `gref`; the new socket is not counted as a session (no `usageInc`). `session_resumed` -> `sessResumed()` re-sends a line DuSu had not answered (once), or finishes an End that was pending (`sessEnding` is also set when DuSu wraps up an interview / practice, so a connection lost before the report still ends in a report), else restores the screen |
| End / typing on a dead connection | End reconnects first, then sends `end`; a line typed in the Home chat on a dead connection is shown, the chat reconnects and the line is sent; a server that cannot be reached leaves "The connection dropped - tap DuSu to carry on" and a tap on the orb tries again (`sessNeedsTap`) |
| Server (`main.py`, additive) | `_replay_into()` seeds `session.transcript` from `resume` (last 60 lines, <= 1200 characters each; junk, roles other than `user` / `assistant` and control characters dropped; adjacent lines by one speaker joined) and sets `session.replayed`. `start {reconnect: true}` (exactly the boolean) with a usable replay in `conversation` / `interview` / `practice` / `home` -> `session_resumed {mode, lang}` and NO opener (no `ai_text`, no `status: starting`, no `home_ready`, no model call). Turn counting: Face-to-Face and Interview `turns = 0` (their first socket already saved and rewarded those turns when it closed - only new turns count); Practice and Home `turns` = the replayed learner lines (a practice is scored once at its end and Home pays nothing at close, so the rounds / the length cap keep their meaning); a practice also takes `elapsed` (clamped 0-7200 s) so the report names the whole duration; Grammar Coach analyses only `transcript[replayed:]` (`_gc_view`) because the first socket's own end-of-session pass already analysed the rest. Anything else - no flag, `"true"`, `1`, an empty / junk / non-list `resume`, Learn - is today's path |
| Words | `sDropped` in both tables. `sw.js` cache `dusu-v35` |

**Gotchas (the other chats).** The replay is read from the DOM (`#feed .msg:not(.thinking)`): a chat that ends on a learner bubble has an unanswered line. After a resume the Face-to-Face / Interview turn caps start again from 0 by design (the interviewer ends by itself; the cap is only a safety net). `stopAllVoice()` forgets the chat (`sessFrame = null`), so a chat that moved on to the `report` / `sessionResult` screens is never revived. A trivial scripted chat earns 0 XP with the fake model scores - a test must spy on the reward call (`db.award_speaker_progress`, `turns == 1`), not read an XP delta. A hidden page cannot listen: on real Chrome a recogniser started while hidden may raise `not-allowed`, which the Home chat answers by switching itself to text mode - hence the single guard in `startListening()`. **Found by an independent review and fixed:** the server handles ONE frame at a time, so while it is still working on an answer, the opener or a report it cannot even read a `ping` - `VP.alive()` therefore gives a busy chat 45 s instead of 3 s and counts ANY frame as proof of life (it used to declare a healthy socket dead and answer the learner's line twice); a revive that is answered by a FRESH opener (nothing was on screen to replay, or an older server ignored the flag) hands `running` back; a line typed while the reconnect is under way waits on screen instead of being sent twice; a Hindi / English switch made mid-chat is re-sent on revive; End tapped during a reconnect waits for the resume (and a forced End while hidden, e.g. a timed Confidence Check, reconnects on return, not in the background); a failed practice scoring clears the pending End; the practice's `elapsed` excludes the time the phone was locked (a practice's duration feeds XP minutes); a huge JSON integer for `elapsed` is caught. **Known and accepted:** if the connection REALLY dies while the server is scoring a practice or building an interview report, the first handler still finishes and saves, and the End re-sent on the new socket scores again (a duplicate attempt) - rare, and only a server-side idempotency key would close it; a revive clears a key-limit / length-cap pause (the next turn meets the same limit again); two lock/unlock cycles within a few seconds of each other can skip the liveness check once. **Still not covered (pre-existing, separate from the lock):** a connection that drops while the page is VISIBLE (a Wi-Fi hiccup, a server restart) leaves these screens with a silent mic and no message - End and typing do reconnect, the mic does not announce it.

**Verified (2026-10-28, scratch infrastructure only):** `tests/daily_voice/`: server selftest **22** (`ping`, the quiet resume, rewards counted once, everything else unchanged); real Chromium -> a WebSocket proxy -> the real server **166**, run three times (the lock in every state, a socket killed while locked, a half-open socket, the 10-minute grace timer on the Playwright clock, a line in flight, rewards, the quota case, Learn, and pins); **the same spec FAILS 48 of 120 checks on the code that was live** (the reproduction: after an unlock the mic is disabled or does nothing and Reply never comes back); **22 planted bugs (6 server + 16 client), all caught** - two survived the first run and each exposed a weak TEST, not a missing guard (a vacuous `dusu_usage` check, and a speech stub whose cancel did not end the utterance); Regression, unchanged: Keys unit 172 + parity 49 + selftest 155 + ws 71 + sw 33 + static 92 + browser 168 + 111 (it pins the Daily mic after a `quota` frame); Job Interview Practice unit 309 + selftest 188 + browser 90 (its `parity_server.py` check "existing registry entries are unchanged", 86 / 87, fails identically on the previous commit - pre-existing); My Day unit 92 + selftest 293 + browser 124 + 137 (one check, "the section, the words and the days in Hindi", failed once under load and passed on the immediate re-run - it asserts text right after a save); Notifications unit 189 + selftest 158; Grammar Coach selftest 88 + WS harness 18 + browser 40 ("Daily and Learn create no row"). **Old = old** against `efdee9b`: everything in the page outside its inline script (markup and CSS) is byte-identical, and the Keys old = old spec passes its 26 text / element-order / static-DOM checks (its 2 "something was added" checks assert the Keys-era diff against `057e58c` and mean nothing against this baseline). **Not verified (only a real phone can):** whether Android Chrome / the Play app keeps the socket across a lock or drops it (both are handled), `SpeechRecognition` coming back after a lock on real devices, TTS behaviour in the background, the Hindi wording of the two new lines.

**Deployed 2026-10-28** - commit `85002a7` (local branch `fix/voice-screen-lock`, cut from `feat/keys-install-notify`; **not pushed**), image `dusu-backend:latest` = `60fd628a6eca`, `sw.js` = `dusu-v34`. No switch (the change only runs when the page is hidden or a socket is gone) and no schema change. Same procedure as section 14: **rollback image** `dusu-backend:pre-voice-lock` (= the previous production image `9bfe6140d134`; `docker tag dusu-backend:pre-voice-lock dusu-backend:latest && docker compose up -d --no-deps backend`) and a **pre-deploy dump** `~/dusu-backups/dusu-before-voice-lock-20261028-104627.sql.gz`; the image was built while the old container kept serving, then tested AS BUILT: its files sha256-identical to the tested tree, `import app.main` clean, and against the code baked into it (`*_BACKEND=baked`, `*_TEST_IMAGE=dusu-backend:latest`) `tests/daily_voice` 22 + 166, Keys unit 172 + selftest 155 + ws 71 + browser 168 + 111, Grammar Coach 88 + 18 + 40, My Day 293 + 124 + 137, Notifications 158 + 109 - all green; then `docker compose up -d --no-deps backend`. **Live check:** clean start, every row count (37 tables) and every rollout switch identical before / after (`key_health`, `keys_ui`, `install_mode`, `notifications` still have no row = off), `sw.js` v34 and the new page code on `localhost:3878`, `dusu.ranabrothers.online` and `dusu.ruralrootcloud.com`, `/health` 200 and `/keys/status` 401 without a login on all three, and a real `ping` -> `pong` over the live WebSocket on all three (so the tunnel carries it). The checks wrote nothing to production. **Please repeat the tester's exact steps on a phone** (Daily -> Chat with DuSu -> turn the screen off -> unlock -> Speak mic and Reply), once in the installed web app and once in the Play / sideloaded app; also try a longer lock (a few minutes) - that is the case where Android may drop the connection and the quiet reconnect has to do its job.

**Verified (2026-10-28, the other chats - scratch infrastructure only):** `tests/daily_voice/` - server selftest for the other chats **125** (`session_resumed` in every mode, no opener, no model call; the replay bounded / joined / sanitised, a smuggled system line refused; Face-to-Face and Interview count only the new turns - spied on the reward call; an Interview can still be finished from a resume; a practice keeps its rounds and its duration; Home keeps its cap; Grammar Coach analyses only the new lines; every other start is today's), the Daily selftest **22**, real Chromium -> proxy -> the real server **335** in `lock2.spec.cjs` at the deploy (Face-to-Face T1-T17, Interview I1-I4, practice P1-P3, Home H1-H10, pins F1-F3; H11 was added afterwards for the one surviving mutant and passes) + **166** in `lock.spec.cjs`. **The first version of `lock2.spec.cjs` (204 checks) FAILS 72 of them on the code that was live** - every one of its 25 behaviour scenarios fails there (after an unlock the mic is dead, the answer never arrives, End never finishes) while its 6 pins pass on the old AND the new code. **An independent review** by a fresh agent (read-only, given only the diff) found 7 issues; each was checked against the code and confirmed - six are fixed with a test that fails without the fix (see Gotchas), the seventh (a revive clears a key-limit pause) and two residual cases are documented there as accepted. **Planted bugs:** 19 server + 16 Daily/Learn + 34 session-chat deliberate bugs (`mutants.sh`), planted one at a time in a copy of the backend and run against the DEPLOYED code: **all 69 are caught.** Three weak spots in the TESTS were found and closed on the way: S11 (the replay bound - the provider layer trims what the model sees, so only a direct check of `_replay_into` proves the server's own bound), N1 (a recogniser restarting itself on a hidden page - T1 now counts recogniser starts during the lock) and N23 (no scenario took a text-mode Home chat through a reconnect - H11). Regression, unchanged: Keys unit 172 + parity 49 + selftest 155 + ws 71 + sw 33 + static 92 + browser 168 + 111; Job Interview Practice unit 309 + selftest 188 + browser 90; My Day unit 92 + selftest 293 + browser 124 + 137; Notifications unit 189 + selftest 158; Grammar Coach selftest 88 + WS harness 18 + browser 40. The same suites pass against the code baked into the built image. Two known artefacts, neither from this change: Job Interview Practice `parity_server.py` 86 / 87 (a registry-entry check that fails on the previous commit too) and Keys "old = old" 26 / 28 - with `3cdbfb0` (the page before this change) as the baseline the 26 identity checks (text, element order, static DOM) pass and the 2 that assert "something was added" are meaningless, because nothing was. **Not verified (only a real phone can):** whether Android Chrome / the Play app keeps the socket across a lock or drops it (both are handled), `SpeechRecognition` coming back after a lock, TTS in the background, the Hindi wording of `sDropped`.

**Deployed 2026-10-28 (the other chats)** - commit `a35a89e` (+ `7e7c44a`, the Android version; local branch `fix/voice-screen-lock`, **not pushed**), image `dusu-backend:latest` = `ced87a7f8759`, `sw.js` = `dusu-v35`. No switch, no schema change. Same procedure as section 14: **rollback image** `dusu-backend:pre-voice-lock2` (= the previous production image `60fd628a6eca`; `docker tag dusu-backend:pre-voice-lock2 dusu-backend:latest && docker compose up -d --no-deps backend`) and a **pre-deploy dump** `~/dusu-backups/dusu-before-voice-lock2-20261028-145316.sql.gz`; the image was built while the old container kept serving and tested AS BUILT (80 source files byte-identical to the tested tree, `import app.main` clean, no `.env` baked in, the suites above against the baked code). **Live check:** clean start, every row count (37 tables) and every rollout switch identical before / after, `sw.js` v35 and the new page code on `localhost:3878`, `dusu.ranabrothers.online` and `dusu.ruralrootcloud.com`, `/health` 200, `/keys/status` 401 without a login, and on all three a real WebSocket `ping` -> `pong` and an unauthenticated `start {reconnect: true}` refused with `auth_error` (nothing created or written). **Android:** `android-twa` is now `versionCode 3` / `versionName "1.2"` - a new signed bundle `android-twa/app/build/outputs/bundle/release/app-release.aab` (and `app-release.apk`) built with the upload key (certificate SHA-256 `EF:02:68:27:...:62:0D`, the one `assetlinks.json` lists). It contains NO native change: the app is a Trusted Web Activity, so the voice fixes reach every installed copy through the website; a new version code is only needed because Play will not take the same one twice. **Please repeat the tester's steps on a phone for Face-to-Face, Interview and the Home chat as well**, with a lock of a few minutes (the case where Android may drop the connection).

---

## 22. "AI busy" - when the AI does not answer: the real cause was DuSu's OWN keys; one calm pop-up; a retry that keeps the words (built and DEPLOYED 2026-10-30; harness `tests/keys/` + `tests/daily_voice/browser/busy.spec.cjs`)

**The report.** A Discord screenshot (28 Oct, 7:08 PM, the owner's phone): after "Hh" in the Home chat the SAME failure appeared twice - an amber banner at the very top ("अभी AI busy है - तुम्हारी keys ठीक हैं। एक मिनट बाद फिर कोशिश करो।", gone after 10 s) and a grey ENGLISH sentence inside the Hindi chat - the words got no answer and nothing could send them again. The owner asked for a proper pop-up, what the message means, and the root cause found and fixed.

**What it really was (measured on 30 Oct with `tests/keys/probe_models.py` and `/health` - not guessed).** DuSu's OWN chain (what the owner rides, and every learner in the quota phase) was nearly all dead, and nothing said so:

| Leg | What it answered | Why |
|---|---|---|
| Groq | 401 rejected | the key died on 6 Oct |
| Gemini | **403 on EVERY chat call** - Google: "The Gemini API free tier is not available for this project. To use the Gemini API, please set up billing..." (and the 2.5 models: "no longer available to new users") | `GET /models` still worked, so `/health` said `gemini: ok` for weeks |
| OpenRouter | 429 "busy upstream" on its one free model | its free pools are saturated |

So "AI busy - try again in a minute" hid a configuration failure that waiting can never fix. Around it, six more causes (all verified in code / logs): (1) one pass over the chain, no second chance; (2) `main._is_quota` guessed from the error TEXT ("429") - a busy provider became "your keys hit their limit" (-> the `quota` frame: an English sentence in the chat and a dead mic), and Job Interview Practice's own copy matched the word "unavailable", which EVERY failed chain contains; (3) after a failed turn Face-to-Face / Interview / Practice talk had no way to continue at all (mic never restarted, no retry; the server kept the unanswered line, so a resend would be said twice), Home lost the typed line, Daily / Learn dropped the spoken one (Learn even SPOKE "Translation unavailable" in English); (4) a failed turn still cost a free daily turn (`TurnQuota.spend` runs before the model call) - only matters in the quota phase (growth phase = unlimited); (5) "your keys are fine" is unknowable, and DuSu's own keys were shown to learners as key rows they cannot fix; (6) the failed chain left NO log line (0 `[keys]` lines in 44 h) and model ids rot silently.

**What the learner sees now.** ONE bottom pop-up (the key pop-up's look, an hourglass, indigo): "DuSu's reply is taking longer than usual / जवाब आने में देर हो रही है" + one plain sentence ("the free AI service behind DuSu isn't answering right now. Free AI gets busy sometimes. It isn't your fault, and what you said is safe") + a countdown from the provider's own wait (`kp.retry_in`; ~6 s for a passing hiccup, 20 s for a busy pool) + ONE automatic retry that sends the SAME words + a **Try again now** button + **Later**. No banner, no second line, no plan / upsell card on a hiccup. "Later" leaves a handle: a `↻ Send again` chip under the unanswered bubble (Home) or "Try again - Tap DuSu" on the orb (voice screens); the mic stays off while the pop-up is open. A learner whose OWN key was rejected still sees that key's card with Replace; DuSu's own keys never appear. Over HTTP (practice scoring, Job Interview Practice, level test ...) nothing is drawn by `KY` - the feature already says it next to what the learner was doing. An opening that fails (the server closes that chat) is opened again by the same button / countdown.

| Piece | Where |
|---|---|
| The frame | `main._is_quota(e)` / `key_error` trust the key engine (`keys/errors.engine_kp`, `is_keys_problem`): only the learner's OWN keys rejected / limited / missing is quota; "the AI did not answer" is never - even with "429" in its text. One helper in the WS loop, `_turn_failed(e, err_type)`, sends the feature's own error frame (`home_error` / `translate_error` / `error`) with `kp` and **refunds the free turn** (`TurnQuota.refund` + `db.refund_request`; opening a socket is itself charged once and stays). Face-to-Face / Interview / Practice take the unanswered line back (`del session.transcript[n_before:]`, turns restored). `resume_interview/service.quotaish` asks the engine first |
| `kp` | gains `own` (the learner's own keys?) and `retry_in` (seconds until it is worth asking again: the soonest key that can recover; none for rejected / blocked / day-limited / gone). For DuSu's own keys: `own: false`, state shown as `transient`, **no key rows** |
| The walker (`providers/openrouter_provider._complete_v2`; `_complete_legacy` untouched = key engine off is exactly today) | ONE short second pass (~1.2-1.8 s, or a limit's own wait when <= 5 s) for a PASSING failure - never for a rejected key, a long limit, a bad request, a background caller (`cool=False`) or when the 30 s ceiling leaves no room; limits PER MODEL (Groq, Gemini; OpenRouter's busy-upstream 429 too - the key is gated only when every model is limited); a model that answers 404 is remembered **per key** for 30 min (`gate.mark_model_gone`; it never counts against the key); a busy shared pool is held 20 s, not 90; ONE rate-limited, safe log line per failed walk (`[keys] chain failed: state=... own=... tried=groq/model:kind-status, ...` - never a key, a learner id or provider text) |
| Config | OpenRouter's free list gains `google/gemma-4-26b-a4b-it:free` (answered valid Hindi JSON in 2 s while the first model said 429); nemotron-3-ultra (slow, broke the JSON) and nemotron-3.5-lightning (empty answers) were tried and left out. **No Gemini model was added**: every Gemini model failed on DuSu's own key, so there was no evidence to choose by |
| Health (`keys/probe.refresh_server_health`, `/health`) | the 10-minute zero-quota probe now also (a) checks every configured model id against the provider's own list (`models_missing`, one log line; an alias such as `*-latest` is never judged, an empty list is "don't know"), and (b) once an HOUR makes ONE tiny real chat call to DuSu's own Groq / Gemini key (OpenRouter excluded: 50 free requests a day) - a key that lists models but is refused every chat now reads `forbidden` / `invalid`, not `ok` (and `usable` drops it). `/health` also carries `models_gone` (what the walker was told does not exist, DuSu's own keys only) |
| Client (`test_client.html`, `sw.js` `dusu-v38`) | `KY`: `paintBusy` / `openBusy` / `retryNow` / `busyDone` (countdown, one automatic retry per failure, paused while the screen is locked), `KY.covers(kp, src)`; the page: `retryTurnInfo()` / `retryLastTurn()`, `sessRetry` (Home / Face-to-Face / Interview / Practice: the unanswered line again on the same socket, or `sessRevive` when the connection is gone or the OPENER failed), `dailyRetry` (`dailyFailedMe`, `dailyOpenerPending`), `learnRetry` (`learnFailedLine`); `HM.onError` / `onQuota` show the chip instead of the server's English sentence; Learn no longer speaks the failure |
| Tools | `tests/keys/probe_models.py` (owner-run: which models REALLY answer the Home prompt with DuSu's own keys - status kind, a bounded provider reason with anything key-shaped removed, latency, valid JSON, Devanagari share; spends a few free-tier requests); the e2e server's test-only `POST /__world/serverkeys {on}` gives DuSu's own chain fake keys |

**What the owner must do (code cannot):** (1) **Gemini** - make a new key from a Google project that HAS free-tier access (aistudio.google.com/apikey -> create the key in a NEW project) or set up billing, exactly as Google's message says, and put it in `backend/.env` `GEMINI_API_KEY`; (2) **Groq** - a new free key at console.groq.com/keys -> `GROQ_API_KEY`; (3) `docker compose up -d --no-deps backend`; `/health.server_keys` shows the truth within the hour (or at once after a restart); (4) optional: $10 of OpenRouter credit lifts its free-model limit from 50 to 1000 a day. Until then the owner's own chats will still fail - but honestly (the pop-up, the retry, a log line, `/health`) instead of "AI busy, your keys are fine".

**Gotchas.** (1) A NEW call site must never guess "quota" from text: use `key_failure(e)` / `is_keys_problem(kp)`. (2) The walker's second pass waits real time: tests replace `op._pause` (`tests/keys/unit.py` `Pauses`); the per-model memory expires together with the key's gate in production - a test that "ends a limit" must age BOTH (`age_limit`). (3) The early probe (`soonest_probe`) now also reaches a model whose memory still says limited (`gate.probe_soonest_model`). (4) The page's `retryTurnInfo` treats "nothing on screen yet" as "the opener failed" - at that moment the socket still LOOKS open for a moment. (5) A countdown number read in a test ticks every second: assert 5-6, not 6. (6) `KY` builds its DOM with `h()` only; ids created at run time (`kyCount`, `kyBar`) are listed in `tests/keys/browser/static.spec.cjs`. (7) The Hindi copy (`busy*` in `KY` `TXT`, `sRetryT` / `sRetryH` / `rtChip` in the page tables) is my draft in the app's style (तुम, DuSu = she) - a native speaker should read it once.

**Verified (2026-10-30, scratch infrastructure only; a fresh Postgres on an `--internal` network, scripted fake providers, no route to the internet).** Keys: unit **228** (was 172), "old = old" walker parity **52** (the two new features are switched off for the SAME scenarios and the walker must equal HEAD; their own behaviour is pinned explicitly), selftest **171**, real WebSocket handler **117** (every mode: transient is never `quota`, no key rows on DuSu's keys, the free turn is given back, the unanswered line is taken back); voice-lock server 22 + 125; Job Interview Practice unit 309 + selftest 188; Grammar Coach 88 + 18; Notifications 189 + 158; My Day 293. Browser (real Chromium -> real app): Keys **208**, key pop-up look 83, install 111, **the new `busy.spec.cjs` 267** (Home typed + voice, Face-to-Face, Interview, viva, Daily, Learn - each failing for real: one pop-up, no banner, no second line, the countdown, ONE automatic retry that sends the same words, the button, "Later" -> chip / orb tap, the mic off while the pop-up is open, an opening that fails, DuSu's own keys vs the learner's own, HTTP features draw nothing, Hindi, an older server's `quota` frame, a locked screen, 360 / 390 / 1280 px, focus, Tab, Escape), voice-lock 166 + 343, Job Interview Practice 90, Grammar Coach 40; client "old = old" with the switches off: the 26 identity checks (text, element order, markup) pass - the 2 "something was added" checks are meaningless against a baseline that already contains the Keys markup (as before). The screenshots (`~/.cache/dusu-dv-shots/busy-*.png`) were looked at. **Planted bugs:** 20 server (`tests/keys/mutants.sh` M45-M65: the quota mislabel, the refund, the unanswered line, own keys shown as rows, a second pass for a rejected key, per-model limits, the model memory, the log line, the early warning, the hourly chat probe ...) and 16 client (`tests/daily_voice/mutants.sh` Y1-Y16: the banner back, a countdown that never fires, an automatic retry that loops, a retry that sends nothing, a countdown that runs while locked, the English line back, a forgotten Daily line, an opener that is not retried, a pop-up that never closes, a hidden rejected key, a dead tap, the mic under the pop-up, a stale chip ...) - **all 36 are caught.** Three server ones SURVIVED the first run and each exposed a weak CHECK, not a missing guard: a definition that no longer matched the code (M45), and two checks that could pass without testing anything (a memory entry that had merely EXPIRED looked "cleared"; "re-adding a key wipes its models" ran with nothing in the memory) - tightened, then caught. **Not verified:** a real phone / the Play app; the Hindi wording by a native speaker; the providers' real busy answers beyond the probe's (Gemini's per-model quota ids are documented by Google and present in the synthetic bodies); a Gemini model on a key that has free-tier access (DuSu's own was refused on every model, so none could be tried).


**Deployed 2026-10-30 (16:22 IST)** - image `dusu-backend:latest` = `564de71cb4b0`, `sw.js` = `dusu-v38`; **not committed at the time** (the owner asked to deploy, not to commit; committed 2026-11-07 - see the note at the top). Same procedure as sections 14-21: **rollback image** `dusu-backend:pre-ai-busy` (= the previous production image `be34b9942d1f`; `docker tag dusu-backend:pre-ai-busy dusu-backend:latest && docker compose up -d --no-deps backend`; no schema change, so nothing else to undo), **pre-deploy dump** `~/dusu-backups/dusu-before-ai-busy-20261030-160040.sql.gz` (62,592 bytes, 37 tables), the image built while the old container kept serving (2 s - only the COPY layers changed), then tested AS BUILT: its 81 source files hash-identical to the tested tree (`4277e034864664b4`), no `.env` baked in, `import app.main` clean (165 routes), `sw.js` v38; and the suites against the code baked into it (`*_BACKEND=baked`, `*_TEST_IMAGE=dusu-backend:latest`): Keys unit 229 / parity 52 / selftest 171 / WebSocket 117, voice-lock 22 + 125, Grammar Coach 88 + 18, Notifications 189 + 158, My Day 293, browser Keys 208, pop-up look 83, install 111, **the busy spec 267**, voice-lock 166 (once 157 + 1: scenario F1 timed out clicking the Daily tab - the same scenario that timed out once on 28 Oct; it passed alone twice and the whole spec passed 166 / 166 on the immediate re-run: a harness hiccup, still unexplained) and 343. Then `docker compose up -d --no-deps backend` (healthy in 8 s). **Live check:** clean startup; every one of the 37 tables' row counts and every rollout switch identical to a snapshot taken just before; `sw.js` v38 and the new page code on `localhost:3878`, `dusu.ranabrothers.online` and `dusu.ruralrootcloud.com`; `/health` 200 and `/keys/status` 401 without a login on all three; a real WebSocket `ping` -> `pong` and an unauthenticated `start` refused with `auth_error` on all three. **The new health check told the truth on its first cycle in production:** `/health.server_keys` = groq `invalid`, **gemini `forbidden`** (it said `ok` for weeks), openrouter `ok`; `usable` = [openrouter]; the log line `[keys] DuSu's own gemini key lists models but is refused every chat call (HTTP 403) ...`; `models_gone` [] and `models_missing` {}. The checks wrote nothing to production except the one tiny real Gemini chat call the hourly probe now makes. **Still the owner's:** replace the Gemini and Groq keys (above), a real-phone run, a native Hindi read.

**Update 2026-10-30 (evening) - the alert says which key is valid or invalid, and leads gently to the plans (built and tested; DEPLOYED 2026-10-31 inside the section 23 batch).** The owner's words: in the alert, "this Groq key valid or invalid, Gemini, OpenRouter - a clear message so the user knows, and slowly they go to our plans; free should make the user used to it and the subscription has no tension, so the free version must be perfect". What the pop-up (`KY.paintBusy`) now shows: (1) **every one of the learner's own keys** (Groq / Gemini / OpenRouter), not only the broken ones, with a plain status - ✅ Working, ❌ Rejected (+ Replace), ⚠ Blocked, ⏳ at a limit, or "Couldn't check right now" - from `GET /keys/status` refreshed by a zero-quota `POST /keys/recheck` when the pop-up opens (client: one per 45 s; server: 4 a minute). **"Working" and "Your keys are working. The free AI service is just busy." appear ONLY when the provider just answered "ok" for that key** (`lastChecked[p] === "ok"`): the full browser run caught that the first version showed "Working" from an OLDER status while the providers could not even be reached. (2) **For the OWNER only**, when it is DuSu's own keys that failed (`kp.own === false`), the frame carries `kp.server` = `{provider: {status, why, at}}` (`main.server_key_view`, from the last probe of DuSu's own keys) and the pop-up lists "DuSu's own AI keys (only you see this)": Groq ❌ Rejected - "Invalid API Key"; Gemini ⚠ Blocked - Google's own sentence; OpenRouter ✅ Working; and "Replace the ones that are rejected or blocked in backend/.env, then restart the backend". `why` is the provider's own sentence (`probe._why_from_body`: the first message of the error body, <= 240 characters, cut at a word, anything key-shaped removed); it is in `Probe.why`, in `refresh_server_health` entries (so in `/admin/overview.server_keys`) and in the owner's frames - **never in `/health` and never in anyone else's frame**. (3) **A plan card** ("Better practice with a DuSu plan - more practice every day, and no keys to find, paste or fix. See plans ›", tappable -> `/subscribe`) on the pop-up for everyone except the owner. **Caveat the owner knows:** the plans page still cannot take payment (Proceed says "payment coming soon"), so the nudge leads to a page that shows the plans but cannot sell them yet - the long-term step, as the owner said, is to build payment. `sw.js` `dusu-v39`. Test tools: the fake world gains `chat_down` (the key is fine, the AI is not: zero-quota checks still answer ok) and `forbidden` (Google's 403 on chat, the list still ok) and a test-only `POST /__world/serverhealth`. **Verified (scratch infrastructure):** Keys unit **234**, selftest **174**, real WebSocket **126**, walker parity 52; voice-lock server 22 + 125; Job Interview Practice 309 + 188; Grammar Coach 88 + 18; Notifications 189 + 158; My Day 293; browser: Keys 208, pop-up look 83, install 111, **the busy spec 299**, voice-lock 166 + 343, Job Interview Practice 90, Grammar Coach 40; client "old = old" with the switches off: the 26 identity checks pass (the 2 "something was added" checks are meaningless against a baseline that already has the Keys markup); **11 more planted bugs (M66-M69, Y17-Y23), all caught**. The screenshots (`~/.cache/dusu-dv-shots/busy-owner-390.png`, `busy-keys-ok-390.png`) were looked at. **Not verified:** a real phone, the Hindi wording by a native speaker.

---

## 23. Product + UI audit fixes (built 2026-10-30, visual-review pass 2026-10-31, DEPLOYED 2026-10-31 - plan + ledger in `DUSU_AUDIT_FIX_PLAN.md`, report in `DUSU_PRODUCT_UI_AUDIT_2026-10-30.md`, harnesses `tests/audit/` and `tests/insights/`)

The owner asked for a product-owner + UI-officer review of the whole app and then "plan it, implement it, QA it, make sure every point is covered". The audit (35 routes x 5 kinds of learner x phone / small phone / desktop / Hindi, plus real clicks through the first run) found three walls in front of a new learner's first spoken sentence - a five-screen key setup, a rewards lecture, a ~20-block Home - plus a heavy first visit, no way to pay and no measurement. Every item now has one status in the plan's traceability matrix: DONE / DONE\* / PARTIAL / OWNER / DEFERRED, each with its proof. Nothing here is behind a rollout switch except the counters (the changes are UI and copy); the one kill switch is `settings.insights` (default ON).

| Area | What changed | Where |
|---|---|---|
| **First run** | The Keys screen for a brand-new learner is a **wizard**: one promise line, "Key 1 of 2", ONE big "Get free key" button (Groq first), ONE paste box that recognises the service from the key's prefix (`gsk_` / `AQ.` or `AIza` / `sk-or-`; quotes and "Bearer " stripped; since 2026-11-07 an `AQ.` key is Gemini - section 24), the second key as two provider buttons, the long guide and videos BELOW, collapsed. It is only a different DRAW of the same save path (`saveKey` / `afterChange`), so there is still one code path that stores a key; a learner who already has keys, or a rollback with the key switches Off, still gets the three-box manage screen. Honest time ("about 5 minutes the first time"), no level-check promise while the level check is OFF, Hindi by default (follows the learner's choice). The four-card rewards sheet opens after the FIRST finished session; "Where we left off" only exists once there is history (`hasHistory()`: the local flag, XP > 0 or a saved promise); a chat under ~30 s says "Too short to score" instead of a red "0 (-64)"; connection errors say "No internet - your chat is safe" and the tap the copy promises works; a cold deep link to a rollout-flagged route (`FLAG_ROUTES`) waits for the first `/me` (and falls back to Home after 12 s if `/me` never answers) | `KY` (`ensureWizard`, `paintWizard`, `wizSave`), `hasHistory`, `maybeShowRewardsIntro`, `renderSessionResult`, `flagPending`, `showBootGate(..., homeAfter)` |
| **Plans** | Rewritten in outcomes true to `PLAN_LIMITS` (Starter 50 / Plus 150 / Pro unlimited AI replies a day - enforced in the "quota" phase; today's growth phase is everyone on their own keys), a Free card, an honest "payment isn't open yet", and **Reserve my plan** (plan + an optional "too high / fair / great") in place of the dead Proceed | `PLN`, `POST/GET /plans/interest` |
| **Analytics** | `backend/app/insights/` (shape of `notify/` and `keys/`): `ev_milestones`, `ev_days`, `plan_interest` (new tables, `create_all`, no ALTER). An allow-list of eight milestones written ONCE per learner (`keys_seen`, `plans_seen`, `install_accepted` come from the client via `POST /ev`; `key1_saved`, `key2_saved`, `first_sentence`, `first_session`, `plan_reserved` only from the server - a browser cannot fake them), active days (IST) from `/me`. The owner sees it on the dashboard ("First-run funnel": per-step counts for 7 / 30 / 90 days, Day-1 / Day-7 return, plan interest) - `GET /admin/funnel`. Counts only: no text, keys, recordings or device data; deleted with the account; the privacy pages say so | `insights/*`, `main._ev*`, `loadFunnel` |
| **Weight of the first visit** | The 1.7 MB logo is no longer on the first screen (a 25 KB WebP); the two web fonts are self-hosted (`assets/fonts`, OFL notice in `OFL.txt`); Google's sign-in script loads only on the login screen; `GET /` (and every other door to the shell - `_page(request)`) carries a WEAK `ETag` + `no-cache` and answers 304 (at the origin - **through Cloudflare no ETag reaches the browser while the page holds a literal email address, see "What the live checks found" below; build 3 fixes it**); versioned assets (`name-v1.ext`) are `immutable` for a year; the service worker shows the cached shell if the network has not answered in 3 s (`NAV_TIMEOUT_MS`) and never stores an error body (`sw.js` `dusu-v40`). **Measured (lab, behind gzip): first visit 2,873 KB -> 429 KB; Slow-4G LCP 8.7 s -> 1.2 s; 3G LCP 34.6 s -> 4.4 s.** The live Cloudflare path can only be re-measured after a deploy (`tests/audit/live.sh`) | `_page`, `_VersionedAssets`, `sw.js`, `loadGIS` |
| **Home** | Hero + Start Speaking, then ONE "today" card (a promise to continue if there is one, else the generic challenge - never both), then 8 tool tiles (Daily Talk, Face to Face Talk, Interview Prep, Learn, Practice Room, Job Interview Practice, Grammar Coach, My Day); the four banners that repeated a tile, the "Your progress" cards and the website footer are gone (Privacy / Terms / Delete my data live in More); the keys card appears only when something needs attention; weekly missions and the career card sit behind one "More for you" row. 3,571 px -> 1,699 px (a brand-new learner 3,548 -> 1,532). **The Hindi / English pill is the first thing in the stack on phones** (it sat at the bottom of the first screen, half behind the nav): `.lg-row` becomes `display: contents` below 1200 px so its pill goes to the top and its one-line note to the end; desktop keeps the row where it was | `HomeMore`, `PROGRESS_TILES`, `syncTodayCard`, `NEWBIE_CHIPS`, CSS near `.lg-row` |
| **Names / copy** | One name per feature everywhere (nav, tile, title, report, Know About, hub): Daily Talk, Face to Face Talk, Learn, Interview Prep (the quick HR mock), Job Interview Practice (resume + job), Practice Room; "My AI keys"; "1 session"; one time style ("8:30 PM", `normTime`); the Interview role is a placeholder; the Beta badge says only "Beta"; the Hindi spoken lines of Learn / Daily AND the Hindi the Home chat shows around DuSu's replies (orb hints, the headphones tip, thinking steps) are all tum (they were "aap": बोलिए, लगाइए, आपके); every message that points to the keys says "More → My AI keys" - 18 of them (and the server's fallback texts) still said "DuSu keys" after the row was renamed | `N` inventory test |
| **UI system** | **Lining numerals** (`font-variant-numeric: lining-nums` on the body; the serif's default digits are old-style - "0" read as "o", "71" as "7I"; two big timers that said only `tabular-nums` fixed); **nothing under 12 px** and a six-step scale as `--fs-*`; the phone header is the logo + one 44 px avatar button (alias / name in Profile, Sign out in More, the dead female button gone, Beta / Day / alias on desktop only); **every control >= 44 x 44** on 34 screens; My Day on one header row with one labelled add button and tabs that fit; one icon set for the More sheet and entries; the brand accent (`--accent`; `--gold` is an honest alias; the report ring and 17 old-gold glows are indigo); Grammar Coach / My Day tabs that fit a 360 px phone; locked badges say how to earn them (`BADGE_HOW`); Ranks lists only learners with XP; Journey labels; the owner dashboard stacks each setting under its text; mood buttons have a name and a word; secondary text lifted from #8a815f (4.46:1) to `--ink-faint` #9a916c (4.7:1 on the lightest card, 6:1 on the page) | CSS + `uiIcon`, `emptyState`, `num100` |
| **Security** | The audit's "148 innerHTML uses" was triaged by a static scan (`tests/audit/innerhtml_scan.py`, 137 sinks) and a dynamic XSS canary: every learner-written or model-written field the server stores is planted with markup and 18 screens, the Home chat and an interview report are walked - nothing may run. Real (self-XSS class) findings were fixed with `esc()` / `num100()`: interview report strengths / fixes, level-test feedback, the timeline's dream / lines, the old today card, the pinned Ranks row, numeric scores | `esc`, `num100` |

**Hinglish writing rule (audit C-9) - one script per feature, never mixed on one screen.** In the NEW features (Home chat and greeting, Know About, My Day, the Keys wizard and the key pop-ups, plans, notifications, install): **Devanagari for the Hindi words + everyday English words in Latin** (about 75% Hindi: the Hindi voice mispronounces romanised Hindi), तुम never आप (never तू), DuSu speaks as a woman and never guesses the learner's gender (no रहे हो / सकते हो), no stiff words (सुप्रभात -> "Good morning"). In the OLD features Roman Hinglish stays where it is shipped on purpose (Daily Talk's replies, the Grammar Coach rule explanations): changing an old feature's script is a separate decision (section 11, "old = old"). A feature's script is declared once, in its own text table.

**Gotchas (found while building - kept as pins).** (1) `node --check` on the page script catches a syntax error, NOT a load-time `ReferenceError` (a top-level `const` used before it exists kills the whole app silently): `tests/audit/verify.cjs` section S loads the page and fails on any script error. (2) Changing `index()`'s signature broke the three internal callers (the SPA fallback for every deep link, a signed-out `/leaderboard` and `/league`) - they all go through `_page(request)` now and `tests/insights` pins every door. (3) Postgres reads `date + $1` as ambiguous: `CAST(:n AS integer)`. (4) The first version of the deep-link fix held a signed-in learner on the spinner and then left the SIGN-IN card showing when `/me` hung; `showBootGate(title, sub, homeAfter)` now sends them Home after 12 s. (5) `display: contents` on `.lg-row` must keep `[hidden]` working (`.lg-row[hidden]{display:none}` is repeated after it). (6) A later CSS rule at equal specificity wins: raising a target to 44 px "at the top" did nothing until the base definition (`.inst-pill`, `.pl-trig`, `.pl-gl`) was edited. (7) `font: inherit` resets `font-variant-numeric` to `inherit`, which is fine; a rule that sets `font-variant-numeric` alone replaces the whole set (numerals are checked by pixel measurement in `verify U`, and by walking `document.styleSheets`). (8) A section of `verify.cjs` that changes the scratch database must put it back (the seeded `next_hook`, the saved language): three of my own failures were a section inheriting what an earlier run left.

**Independent review (a fresh agent read the diff cold; nine findings, every one reproduced or rejected before acting).** Fixed, each with a check that failed first: (1) **a bug in production today** - the Home "Your AI keys" card re-asked a failing `GET /keys/status` in a tight loop (`paintCard -> refreshStatus -> fail -> paintAll -> paintCard`): **1,423 requests in 6 s** measured against the page as deployed, with the endpoint failing or the phone offline; now a 30 s pause after a failed ask (the learner's own tap still asks); (2) "has history" no longer depends on Journey XP alone (Face to Face / Interview / Practice add speaker XP and sentences, not Journey XP) and the Ranks hint tells the truth; (3) "No sentences yet" only when nothing was said, else "Session saved."; (4) the service worker stored the privacy / terms / account-deletion pages as the app shell and showed them in its place on a slow connection - they now go straight to the network; (5) the service worker kept 502 / 503 answers for fonts and icons - only good answers are cached; (6) the wizard wiped a second key pasted while the first was saving; (7) a saved price opinion could be un-pressed although the server never erases one; (8) the "had a session" flag is now per account, not per device; (9) `--glass-brd` is a plain rgba (no `color-mix()` in a custom property). Left as they are, on purpose: the plans page is Hindi without a toggle when the bilingual switch is off (the §11 rule for new copy); the plan numbers (Free 500 vs Starter 50 on DuSu's keys) are an owner decision (plan 5.5); two XPs (plan 5.10).

**Fresh-eyes visual review of the FINAL screens (2026-10-31; plan 7.5b has the 20-row table).** After the batch was done, a fresh agent that had not seen any of the work was given ~80 final screenshots (phone, 360 px, desktop, Hindi; zoomed crops and pixel measurements) and asked only for visual / UX defects: no High, 20 findings. Each was checked against the screenshot and the code first. **Fixed - every one with a check that fails on the page as it was before (`verify.cjs` section Y, `OLD_HTML=tests/audit/.out/pre-vr.html`: 33 of its 41 checks fail there) and a planted bug it must catch:** the plans page says why "Reserve my plan" waits ("Tap a plan above to choose it") and marks the chosen plan with a radio ring; My Day's summary wraps (two lines at most) instead of being cut; the profile's leaderboard alias is not broken in the middle of the word (`.pf-email`'s `break-all` was inherited by the alias line); Journey's trend row never wraps its numbers, the dates read "30 Oct" and the chart is drawn only from 3 or more distinct days; an empty session result shows a dash and "Nothing to score yet" instead of loading dots under "Session complete"; Grammar settings' data buttons stack and say "Download my data" like My Day and Job Interview Practice; the key block's dotted underline hugs "Get free key" and Remove is tinted; the header avatar's initial is dark (`.userchip span` had out-ranked `.uav-init`: 1.6:1 -> 5.6:1); the five mood buttons share one row; the weekly league tells a learner who is not on the board how to get on it, and the Ranks subtitle reads "Others see you as <alias>"; Interview Prep's Practice-hub icon is the briefcase (the sliders read as Settings); the Hindi priority chip says "ज़रूरी" (important), not "ज़्यादा" (more); the two "Consistent Speaker" badges are different names (the hours one is "Marathon Speaker"), "DUSU" -> "DuSu"; the key wizard's guide scrolls into view when opened.

**One of the findings was a real bug in production, not a look.** `Progress.streak_days` and `sessions_today` are stored and only change when the learner next practises, so **every learner who practised yesterday saw yesterday's session count as "today's" every morning, and a streak that died a week ago stayed "alive"** (the lapsed learner of the audit: `/me` said streak 4 and 2 sessions today after 8 days away). `db._live_counters(prog)` now gives both as of today on the IST day: the streak is alive only if the last practice was today or yesterday, sessions today is 0 on a new day; used by `/me` (`_state`), the Home streak chip (`build_growth().streak`) and the owner dashboard card; the stored values and the confidence composite are untouched, and a read never writes. Unit 10 + scratch-Postgres 6 checks (`tests/insights`), planted bugs M33-M38 all caught. **Same root cause, deliberately NOT changed:** `build_today` (the Home "today" card) also reads the stored `sessions_today == 0`, so its "Keep your N-day streak alive" branch (needs `last_active == yesterday` AND `sessions_today == 0`) can practically never fire (a practice yesterday leaves `sessions_today` at 1 or more); a one-line fix would make that card appear on Home each morning - the owner's call.

**Not changed - owner / product, with the recommendation (plan 7.5b):** "Starter" is both the first XP rank and the cheapest paid plan (recommend renaming the rank, e.g. "Beginner": client `RANK_LABELS` + `rankLabel`, `life._RANK_LABELS`, the rewards text); the two XPs (5.10: the weekly league counts Speaker XP, Journey shows lesson XP, so a weekly total can exceed the all-time number); Hindi headings are a heavy system sans next to a light serif Latin (a Devanagari serif is 100+ KB against the weight work; a lighter weight is the cheap alternative); the career screen says "Not set yet" while Journey shows the dream from the level check (prefilling the career box from it is a one-line change, held back because "speak fluently" makes a poor career path); and **a new finding: Grammar Coach's "How much to show" (Auto / Gentle / Standard / Strict) and "Natural-English tips" (On / Off) are saved but read by NOTHING** - the analysis and the screens ignore both (the plan promised the strictness as a display cap by level), so two controls in a live feature do nothing: wire them or hide the two cards. **Not a bug:** the gap before the Hindi danda - the source has none (334 attached, 0 spaced); it is the glyph of Noto Sans Devanagari (measured: "करें।" = "करें" + "।" exactly).

**Tools.** `tests/audit/` (README inside): `up.sh` / `down.sh` start a scratch Postgres on an internal network + the real app with a fake model and seeded learners (a brand-new one, one with keys, an active one with a month of practice, a lapsed one, the owner, nine league rivals) under PRODUCTION's switches; `walk.cjs` / `flows.cjs` / `race.cjs` / `a11y.cjs` photograph and measure; **`verify.cjs` asserts** (sections S K R P F O H N U W V Y X, 307 checks; `OLD_HTML=<page before the fixes>` must make them fail - that is how each check is shown to discriminate: `.out/before.html` for U / W / X, `.out/pre-vr.html` for Y); `mutants.sh` plants 48 client bugs plus a control; `perf.cjs` measures the first visit; `live.sh` / `live_gis.cjs` measure the LIVE page and check Google's real sign-in button (read-only - run before and after a deploy); `AUDIT_IMAGE=dusu-backend:latest AUDIT_BACKEND=baked up.sh` serves the app from a BUILT image; `compare.py` diffs two sweeps. `tests/insights/` (README inside): unit / scratch-Postgres / WebSocket tiers + 42 planted bugs.

**Owner items (code cannot do these):** replace DuSu's own Gemini and Groq keys (section 22); "taste first" and "one key to start" are product decisions (plan 5.2 / 5.4); payment (5.5); the retention-loop go-live runbook (5.3: Install -> Notifications -> WhatsApp, each on a real phone first); the day-1 / 2 / 3 path (5.6); a native Hindi read (5.7); a real-phone pass incl. TalkBack and the large-font setting (5.8); the deploy decision (5.9); and, from the visual review (plan 7.5b): the rank-vs-plan name "Starter", the Devanagari headings, the career box vs the dream, the two decorative Grammar settings (wire or hide), and `build_today`'s streak-at-risk card (the same stale-counter root cause).

**Deployed 2026-10-31 (two builds went out and build 2 is live now; a third is built, tested and waits for the owner's go-ahead; the whole batch was committed 2026-11-07 - see the note at the top).** Procedure as in sections 14-22. **Build 1** (image `836d0b7fe4f9`, 09:20 IST) and **build 2** (image `301a73d4ebf6`, 10:09 IST - **live now**). Rollback images: `dusu-backend:pre-audit-fixes` (= `564de71cb4b0`, what production ran before today), `dusu-backend:pre-etag-mime` (= `836d0b7fe4f9`) and `dusu-backend:pre-email-etag` (= `301a73d4ebf6`, the rollback target for build 3); pre-deploy dumps `~/dusu-backups/dusu-before-audit-fixes-20261031-092022.sql.gz` and `dusu-before-etag-mime-20261031-100908.sql.gz`. Each image was built while the old container kept serving and tested AS BUILT: all 112 files hash-identical to the working tree, no `.env` inside, `import app.main` clean (169 routes), then every suite against the code baked into it (`tests/audit/verify.cjs` 302 / 305 / 307 for builds 1 / 2 / 3 via the new `AUDIT_BACKEND=baked`; insights, keys, voice-lock, My Day, Notifications, Grammar, every browser spec; the Resume Interview suites have no baked mode and ran against the tree, which is byte-identical). Live check (read-only) on `localhost:3878`, `dusu.ranabrothers.online` and `dusu.ruralrootcloud.com`: clean startup log; the row count of every table identical before / after except the three new EMPTY tables `ev_days`, `ev_milestones`, `plan_interest`; every rollout switch identical; `sw.js` v40 and the new page on all three; the new endpoints (`/ev`, `/plans/interest`, `/admin/funnel`) and the old ones answer 401 without a login; a real WebSocket `ping` -> `pong` and an unauthenticated start refused on all three; and **Google's own sign-in button renders on the live login page** (`tests/audit/live_gis.cjs`, run first on the OLD page as a control - Google's script now loads lazily and the offline sandbox has no route to Google, so only the live site can show it).

**What the live checks found that the lab could not (kept as pins).** (1) The new font and the WebP logo were served as `text/plain` (Starlette's answer for an extension the slim image's mime table does not know) - fixed in build 2 (`mimetypes.add_type`); Cloudflare's edge still holds the old cached copies of the two files (versioned names, cached for a year) until the owner purges them - optional, cosmetic, browsers sniff both. (2) **No ETag reaches a browser through Cloudflare - strong or weak - while the page holds an email address**: Cloudflare's "Email Address Obfuscation" rewrites the one `mailto:` link in the HTML, injects a SYNCHRONOUS `email-decode.min.js` ahead of the app's own script (a blocking request on every first visit, invisible in the lab) and, because it changed the body, drops the ETag - so no repeat open could be a 304 and every open re-downloaded the page (~385 KB over the wire). Build 2 made the ETag weak (right in itself; the origin answers 304 to either form). **Build 3 (`d57621b7ea9f`: the support address is assembled in `openHelp()` and never written in the markup; `verify.cjs` N, `tests/insights` M42, client mutants m48 / m49) is built and tested as built (all 32 suites green, audit 307 / 307) but NOT live: it waits for the owner's explicit go-ahead.** Until then every app open re-downloads the page. (3) The Cloudflare zone rewrites the cache header of PNG icons (`max-age=14400`); the origin sends `immutable`. (4) Measured live (`tests/audit/live.sh`, throttled, before build 3): a first visit is ~0.66 MB (the page ~385 KB, Google's sign-in script ~112 KB, fonts ~139 KB, images ~25 KB); the lab cannot see the service worker's own fetch, so the repeat-open saving is measured directly after build 3 (`curl` a conditional GET through Cloudflare). (5) Docker on this box can bind-mount only paths under the repo (not `/tmp`): a tool that needs a file mounted must live in the repo or read it from stdin.

**One test race found and fixed - the product was right.** In a 33-suite run `busy.spec.cjs` E3 failed once: the pop-up's "Working" chips can show from the last known status while the real check is still on its way (the header then says "Checking..."), and the sentence "Your keys are working" is claimed only after the providers answered; E3 asserted it the instant the chips appeared. E3 now waits for the sentence, and E3b holds the real check open (a parked request) and pins the order; planted bug Y24 (the header never says it is checking) is caught. The busy spec is 308 checks. The failing run's own screenshot (`busy-keys-ok-390.png`) showed the in-flight state - read it before blaming the code.

---

## 24. Gemini keys that start with `AQ.` (fixed 2026-11-07, NOT deployed yet - harness `tests/keys/browser/gemini.spec.cjs`)

**The report:** "I add my Gemini key, tap Save and nothing happens - Groq and OpenRouter save fine". **Root cause:** since 2026-05-28 Google AI Studio hands out ONLY keys that start with `AQ.` (its "auth keys"; old `AIza` keys are being retired by Google). The first-run wizard (`KY` in `test_client.html`) treated `AQ.` as "a short-lived token" and returned early in `wizSave` - it repainted the same red line the paste had already drawn, so Save looked dead, and **no request ever reached the server** (measured: 0 calls to Google in the reproduction; the tester's own timeline shows 13 minutes on the wall before they gave up and used OpenRouter). The belief was false: DuSu's own server key is an `AQ.` key and has worked since 2026-09-21. **Second bug (measured against Google):** a wrong / cut / mistyped `AQ.` key gets HTTP 400 `"Invalid Auth key."` (an `AIza` key gets "API key not valid"); `classify._INVALID_WORDS` did not know that wording, so it read as `bad_request` -> the learner was told "Couldn't reach Gemini".

| Fix | Where |
|---|---|
| `AQ.` is Gemini | `PREFIX` gemini = `/^(AIza|AQ\.)/`; both early returns (the paste handler and `wizSave`) removed |
| True words | `gemHint` (EN + HI): "New Gemini keys start with AQ. (older ones with AIza)"; guide step 4 and the Gemini placeholder name both prefixes |
| Never a dead end | a refused Gemini key in the wizard adds `ksGemSkip`: "You don't need Gemini: any two of Groq, Gemini and OpenRouter will do" |
| Server | `"invalid auth key"` added to `classify._INVALID_WORDS` (still evidence-only: a 400 about anything else stays `bad_request`) |
| Shell | `sw.js` `dusu-v41` |

**Verified (2026-11-07, scratch infrastructure only):** `gemini.spec.cjs` 29 / 29 (an `AQ.` key recognised, sent, stored as `AQ.••••<last four>`, the wizard moves on and takes the learner in; a wrong `AQ.` key is "didn't accept", never "couldn't reach", nothing stored, the right one right after is saved; the manage screen; Hindi) - **17 of its checks fail on the code before the fix**; unit 235 (new: Google's `AQ.` wording), selftest 176 (new: a wrong `AQ.` key is `invalid` and not stored, a good one is saved and masked), `keys.spec.cjs` 212, static 92, sw 62; the audit check P0-1 that asserted the OLD behaviour now asserts the new one. **Not verified:** a fresh free key from a project other than the owner's (Google has reported 401s for `AQ.` keys on some accounts and a 403 "free tier not available for this project" that came and went on 2026-10-28..30 - outside DuSu's control, which is why the wizard now says Gemini is optional).

---

## Quick command reference

```powershell
# Local run — from repo root, backend served on 127.0.0.1:8000
cd "C:\Personal Work\English Specking\backend"
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# health check: http://127.0.0.1:8000/health
```

```bash
# Import check — run from backend/; catches runtime import / NameErrors a syntax check misses
backend/.venv/Scripts/python -c "import app.main"
```

```bash
# Android build — from android-twa/; JAVA_HOME must be a real standalone JDK 17 (not the Studio JBR)
export JAVA_HOME="/c/Program Files/Microsoft/jdk-17..."   # PowerShell: $env:JAVA_HOME = "C:\Program Files\Microsoft\jdk-17..."
cd android-twa
./gradlew assembleRelease bundleRelease   # → app-release.apk (share THIS; copy to repo root as DuSu-app.apk) + AAB for Play. Never share assembleDebug output (browser bar).
```

```bash
# Deploy — Render auto-deploys on push to main; then poll the live URL to confirm it went out
git push origin main
curl -s https://dusu-app-1.onrender.com/health
```

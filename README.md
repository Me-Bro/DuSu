# DuSu — Speak with Confidence

**DuSu** is a **voice-first AI English-speaking coach**. You talk out loud; DuSu listens (browser speech-to-text), thinks (an LLM), and replies with a spoken voice (browser text-to-speech). It's built as a **companion, not a lesson app** — a warm mentor who remembers you across sessions, notices your mood, and holds one ongoing relationship across every practice mode. No grammar drills or flashcards — it trains the thing people actually freeze on: *speaking to another human under pressure*.

Target users: Indian, mobile-first, budget-Android learners who know some English but freeze speaking it — freshers/students prepping for job interviews and campus placements, non-metro/non-native speakers building daily speaking confidence.

Cost model: **$0 running cost** — free LLM provider tiers + free browser speech APIs.

---

## What it does

Four speaking modes, all over one WebSocket (`/ws/interview`):

| Mode | What it does |
|---|---|
| **Talk** (conversation) | Free, warm English chat that never ends; follows your interests |
| **Interview** | Adaptive mock HR interview, self-ends, then gives a scored report (grammar, fluency, confidence, communication, vocabulary, professionalism + a rewritten "better answer") |
| **Learn** | Say a Hindi/Hinglish sentence → get the natural spoken-English translation |
| **Daily Talk** | Hindi-first "close friend" day chat — check in on your day, get a gentle nudge back to practice |

Plus: a dynamic AI-generated level test (CEFR A0–B2) on first login, a 7-level roadmap ("The Village" → "The Global Stage") with lessons + boss tests, XP/streak/badges, a persistent emotional memory (nickname, dream, moments, relationship stage), and a weekly "letter" from DuSu.

Ships as a **single-file web app** (no build step), installable as a **PWA**, and wrapped as an Android **TWA** (Trusted Web Activity — needed because a plain WebView doesn't support the Web Speech API).

For the full product spec (all 4 modes, memory system, roadmap, monetization notes, every `.md` plan doc) see **[CLAUDE.md](CLAUDE.md)**.

---

## Architecture (short version)

```
Browser (Chrome/Edge)                     FastAPI backend
  mic → SpeechRecognition (STT)  ─┐         /ws/interview  (all 4 modes)
  speaker ← speechSynthesis (TTS) ─┼─ text ─ HTTP endpoints (auth, roadmap,
  backend/test_client.html         │         admin, BYOK keys, assessment)
  (one ~4000-line HTML/JS/CSS file)┘              │
                                                    ▼
                               Free LLM chain (OpenAI-compatible):
                               groq → gemini → openrouter → github
                               (auto-failover, per-provider cooldown)
                                                    │
                                                    ▼
                               Postgres — the `db` service in this
                               repo's docker-compose.yml (self-hosted;
                               empty DATABASE_URL = fully stateless)
```

Speech never leaves the browser — the WebSocket wire carries **text only**. The LLM is the brain, never the ears/voice.

| Layer | Choice |
|---|---|
| Frontend | Single HTML file, vanilla JS/CSS, PWA + Android TWA — `backend/test_client.html` |
| Backend | FastAPI + one WebSocket — `backend/app/main.py` |
| LLM | Multi-provider free-tier fallback chain — `backend/app/config.py`, `backend/app/providers/` |
| Auth | Google Sign-In → HMAC-signed stateless session token — `backend/app/auth.py` |
| DB | Self-hosted Postgres (`db` service in `docker-compose.yml`), SQLAlchemy 2.0 async, graceful no-DB degrade — `backend/app/db.py` |
| Hosting | Docker Compose on the host box (app + Postgres), fronted by cloudflared |

---

## Repo layout

```
backend/            FastAPI app (app/) + the entire frontend (test_client.html) + PWA assets
android-twa/         Android Trusted Web Activity wrapper (current, ships voice-capable APK)
android-launcher/    Deprecated Android shim (kept for side-by-side install only)
cloudflare/          Planned local-first edge failover (Worker + tunnel) — not deployed yet
*.md                 Product/architecture/plan docs (CLAUDE.md is the main one — read it first)
```

---

## Quick start (local dev)

### Prerequisites
- **Python 3.12.7** (`backend/runtime.txt`)
- **Git**
- At least **one** free LLM API key (Groq, Gemini, OpenRouter, or GitHub Models)
- **Docker + Docker Compose** — brings up the app *and* its Postgres. (Running bare with an empty `DATABASE_URL` still works, just stateless: no memory/XP/roadmap.)
- (optional) **Google Cloud OAuth client** — for Google Sign-In locally
- (optional) **JDK 17** + **Android SDK** — only if building the Android APK

No Node/build tools needed for the web app — it's plain HTML/JS/CSS served as-is.

### 1. Clone

```bash
git clone git@github.com:Me-Bro/DuSu.git
cd DuSu
```

### 2. Backend venv

```bash
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install --upgrade pip      # Windows
.venv/Scripts/python -m pip install -r requirements.txt
```
(macOS/Linux: `.venv/bin/python` instead of `.venv/Scripts/python`.)

### 3. Configure `backend/.env`

```bash
cp .env.example .env
```

Fill in (from `backend/app/config.py` — the source of truth):

```bash
# --- LLM keys — need AT LEAST ONE. Chain order: groq -> gemini -> openrouter -> github ---
GROQ_API_KEY=
GEMINI_API_KEY=
OPENROUTER_API_KEY=
GITHUB_TOKEN=

# --- Google Sign-In (optional — leave empty to run without login, dev only) ---
GOOGLE_CLIENT_ID=
SESSION_SECRET=change-me-to-a-long-random-string

# --- Database (optional — empty = stateless mode) ---
DATABASE_URL=

# --- Server ---
HOST=0.0.0.0
PORT=8000
```

Free key sources: [Groq](https://console.groq.com/keys) · [Gemini](https://aistudio.google.com/apikey) · [OpenRouter](https://openrouter.ai/keys) · a GitHub PAT with `models: read` for GitHub Models.

Google Sign-In (optional): console.cloud.google.com → APIs & Services → Credentials → OAuth client ID → type "Web application" → Authorized JS origin `http://localhost:8000` → paste Client ID.

Database: nothing to sign up for. `docker compose up -d` (the production run — code baked into the image; for hot reload add `-f docker-compose.yml -f docker-compose.dev.yml`) starts Postgres alongside the app and injects `DATABASE_URL` from the `POSTGRES_*` vars in the root `.env`; tables and migrations auto-run on startup (`db.init_db()`). Data lives in the `pgdata` volume — `docker compose down -v` destroys it. To move the data to another host, use `backend/scripts/migrate_db.py`.

### 4. Run

```bash
cd backend
.venv/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000/**. Sanity check:
```bash
curl -s http://127.0.0.1:8000/health
# {"ok":true,"has_key":true,"providers":["groq", ...]}
```
Empty `providers` list → no key loaded, double-check `.env` is under `backend/` and key names match exactly.

### 5. Before trusting any backend change

```bash
backend/.venv/Scripts/python -c "import app.main"
```
Catches runtime import/`NameError`s that a plain syntax check misses — a real gotcha here (see `CLAUDE.md` §8.7).

---

## Roles

Two hard-coded emails in `backend/app/main.py` get elevated access (owner = full admin + unlimited default-key use). Everyone else must add ≥2 verified free API keys of their own once `require_own_keys` is on (protects the shared free LLM quota — this is a $0-cost product).

---

## Android app (optional)

Only needed to rebuild the APK:

```bash
export JAVA_HOME="/path/to/jdk-17"     # must be a REAL standalone JDK 17, not Android Studio's bundled JBR
cd android-twa
# create android-twa/local.properties with: sdk.dir=<your Android SDK path>
./gradlew assembleDebug                # -> app/build/outputs/apk/debug/app-debug.apk
```
To regenerate icons after a logo change: `backend/.venv/Scripts/python.exe android-twa/gen_icons.py`.

---

## Deploying

- Root dir: `backend/`. Build: `pip install -r requirements.txt`. Start: `backend/Procfile` → `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
- Set the same env vars as `.env` in your host's dashboard (Render, etc.) — production doesn't read `backend/.env`.
- Free-tier hosts (e.g. Render) sleep after idle — cold start ~30-50s, expected.

---

## More docs

- **[CLAUDE.md](CLAUDE.md)** — full product + architecture reference: every mode, the DB schema, the LLM prompt system, every frontend flow, Android/Cloudflare/deploy details. Read this before making non-trivial changes.
- **[INSTALLATION.md](INSTALLATION.md)** — migration-focused install guide (moving the repo to a new machine, icon swap steps, troubleshooting table).

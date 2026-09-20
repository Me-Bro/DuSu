# DuSu — Installation Guide (new machine setup)

> Full setup for moving this repo to a fresh laptop/PC. Read `CLAUDE.md` first for what DuSu *is* (product, architecture, all files) — this doc is only the "get it running" steps.

Repo: `git@github.com:davidrana123/dusu-app.git` (branch `main`)
Live: https://dusu.ruralrootcloud.com (self-hosted Docker + cloudflared tunnel; deploys via PR merge to `main`)

---

## 0. Same-owner machine move (fastest path — do this, skip §2/§4)

If you're moving this same repo folder to another machine **you** own, don't re-clone + re-enter keys from scratch. `backend/.env` already has all 4 real LLM keys, `GOOGLE_CLIENT_ID`, `SESSION_SECRET`, and `DATABASE_URL` filled in — nothing redacted, nothing hidden. Just carry the file over:

1. Copy/zip the whole `DuSu` folder to the new machine (USB, cloud drive, `robocopy`, whatever) — **including** `backend/.env` and `.git`.
2. **Skip copying `.venv/`** — Python venvs bake in absolute paths and don't survive a move. Recreate it fresh on the new machine (§3), then reuse the copied `.env` as-is (no edits needed).
3. Everything else (keys, DB URL, session secret) just works — go straight to §3 (venv) then §5 (run).
4. Only machine-specific file to redo: `android-twa/local.properties` (`sdk.dir=...`) if you'll build the APK there — SDK path differs per machine.

Rest of this doc (§1-§9) is the from-scratch path — useful as reference or if setting up a second/clean machine instead.

---

## 1. What you need before you start

| Tool | Version | Why |
|---|---|---|
| **Git** | any recent | clone repo, push |
| **Python** | **3.12.7** (`backend/runtime.txt`) | backend runs on this exact minor version on Render; use same locally |
| **A code editor** | VS Code / Claude Code | — |
| (optional) **JDK 17** standalone | 17.x | only if building the Android APK |
| (optional) **Android SDK** (API 34) | — | only if building the Android APK |
| **Docker + Docker Compose** | — | brings up the app *and* its Postgres (`db` service). Running bare without a `DATABASE_URL` still works — stateless mode, no memory/progress/roadmap |
| (optional) **Google Cloud OAuth client** | — | only if you want Google Sign-In locally |
| At least **one** free LLM API key | Groq / Gemini / OpenRouter / GitHub Models | the app needs at least one working key to think |

No Node.js, no build tools needed for the web app — `backend/test_client.html` is plain HTML/JS/CSS, served as-is.

---

## 2. Clone the repo

```bash
git clone git@github.com:davidrana123/dusu-app.git "DuSu"
cd DuSu
```

(If you don't have SSH keys set up on the new machine yet, use the HTTPS remote instead, or set up `ssh-keygen` + add the public key to GitHub first.)

---

## 3. Backend setup (Python venv)

From repo root:

```powershell
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements.txt
```

(Bash equivalent: `python3 -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt`)

`.venv/` is git-ignored — always recreated fresh per machine.

---

## 4. Create `backend/.env` (secrets — never commit)

Copy the template and fill in:

```bash
cp .env.example .env
```

`backend/.env` fields (from `backend/app/config.py` — this is the source of truth, more current than `.env.example`):

```bash
# --- LLM provider keys — need AT LEAST ONE. Empty ones are skipped. ---
# Chain order (config.py): groq -> gemini -> openrouter -> github
GROQ_API_KEY=
GEMINI_API_KEY=
OPENROUTER_API_KEY=
GITHUB_TOKEN=

# --- Google Sign-In (optional; leave empty to run without login, dev only) ---
GOOGLE_CLIENT_ID=
SESSION_SECRET=change-me-to-a-long-random-string

# --- Database (optional; empty = app runs fully, just stateless) ---
DATABASE_URL=

# --- Server (defaults are fine locally) ---
HOST=0.0.0.0
PORT=8000

# --- Android TWA asset-links (only needed if serving assetlinks.json for the app) ---
ANDROID_TWA_PACKAGE=com.dusu.app
ANDROID_CERT_SHA256=
```

Where to get keys (all free tiers):
- **Groq** — https://console.groq.com/keys
- **Gemini** — https://aistudio.google.com/apikey
- **OpenRouter** — https://openrouter.ai/keys
- **GitHub Models** — a GitHub PAT with `models: read` permission

Google Sign-In (optional): console.cloud.google.com → APIs & Services → Credentials → Create OAuth client ID → type "Web application" → Authorized JavaScript origin `http://localhost:8000` → copy Client ID into `GOOGLE_CLIENT_ID`.

Database: nothing to sign up for — it's self-hosted. `docker compose up -d` (production; add `-f docker-compose.yml -f docker-compose.dev.yml` for a hot-reload dev loop) starts Postgres beside the app and injects `DATABASE_URL` from the `POSTGRES_*` vars in the root `.env`, so `DATABASE_URL` in `backend/.env` stays empty. The app auto-creates tables + runs migrations on startup (`db.init_db()`). Data lives in the `pgdata` volume; `docker compose down -v` destroys it. Copy data to another host with `backend/scripts/migrate_db.py`.

---

## 5. Run it locally

```powershell
cd backend
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000/ — the whole app (login, home, practice modes, admin) loads from that one page.

Sanity check:
```bash
curl -s http://127.0.0.1:8000/health
# -> {"ok":true,"has_key":true,"providers":["groq", ...]}
```
If `providers` is empty, no LLM key loaded — check `.env` is in `backend/` (not repo root) and the key names match exactly.

**Import check before trusting a change** (catches runtime `NameError`s a syntax check misses):
```bash
backend/.venv/Scripts/python -c "import app.main"
```

---

## 6. App icon / logo

Web app icon lives at `backend/logo.png`, served at `/logo.png` and referenced by `backend/manifest.webmanifest` (PWA icons) and `backend/test_client.html`. To change it: replace `backend/logo.png` directly (any reasonably square PNG works — browsers scale it) and bump the service-worker cache version in `backend/sw.js` (`const CACHE = "dusu-vN"`) so installed/cached clients pick up the new icon.

The master brand copy at repo root, `Logo.png`, and the Android icon source `android-twa/icon-master.png`, should be kept in sync with `backend/logo.png` (same image) — the Android build regenerates its mipmaps *from* `icon-master.png` (see §8).

---

## 7. Roles / owner access

Two emails are hard-coded in `backend/app/main.py`:
- `OWNER_EMAILS = {"david123rana@gmail.com"}` — full admin (`/admin/*`) + unlimited default-key use.
- `UNLIMITED_EMAILS = {"shuhanisuhana037@gmail.com"}` — unlimited default-key use, no admin.

Everyone else is `role="user"` and, once `require_own_keys` is ON (default), must add their own LLM keys (min. 2 verified) via the in-app Keys screen before using the app.

---

## 8. Android app (TWA) — optional

Only needed if you're rebuilding the APK. Skip this section for pure web dev.

**One-time per machine:**
1. Install a **standalone JDK 17** (not the Android Studio bundled JBR — it breaks this Gradle/AGP config). Set `JAVA_HOME` to it.
   ```powershell
   $env:JAVA_HOME = "C:\Program Files\Microsoft\jdk-17..."
   ```
2. Install Android SDK (API 34) — via Android Studio's SDK Manager, or command-line tools.
3. Create `android-twa/local.properties` (git-ignored, machine-specific):
   ```
   sdk.dir=C:\\Users\\<you>\\AppData\\Local\\Android\\Sdk
   ```

**Regenerate icons from `icon-master.png`** (after replacing the logo, §6):
```powershell
backend\.venv\Scripts\python.exe android-twa\gen_icons.py
```

**Build:**
```bash
cd android-twa
./gradlew assembleDebug     # -> app/build/outputs/apk/debug/app-debug.apk
```
Copy the built APK to repo root as `DuSu-app.apk` if you want to ship it as-is.

Release build needs `android-twa/keystore.properties` (git-ignored: `storeFile`/`storePassword`/`keyAlias`/`keyPassword`). Without it, `assembleRelease` still runs but produces an unsigned APK — use debug for testing.

**Full-screen (no Chrome address bar)** requires Digital Asset Links to verify both ways: the app already trusts `dusu.ruralrootcloud.com` (`strings.xml`); the server needs `ANDROID_CERT_SHA256` set (get it via `keytool -list -v` on your keystore) so `GET /.well-known/assetlinks.json` returns the right fingerprint.

---

## 9. Deploying (Render — already live, no setup needed unless standing up a new instance)

- Root dir: `backend/`. Build: `pip install -r requirements.txt`. Start: `backend/Procfile` → `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
- Push to `main` → Render auto-deploys.
- Set the same env vars from §4 in the Render dashboard (nothing reads `backend/.env` in production — Render injects real env vars).
- Free tier sleeps after ~15 min idle (cold start 30-50s) — expected, not a bug.
- After deploy, confirm it's actually live before declaring done:
  ```bash
  curl -s https://dusu.ruralrootcloud.com/health
  ```

---

## 10. Common gotchas

| Symptom | Cause / fix |
|---|---|
| `providers: []` in `/health` | No LLM key loaded — check `.env` is under `backend/`, not repo root |
| Logo/icon doesn't update in browser | Bump `CACHE` version string in `backend/sw.js`, hard-refresh |
| Android build fails on Gradle/AGP toolchain | `JAVA_HOME` pointing at Android Studio's bundled JBR instead of a real JDK 17 |
| Login doesn't work locally | `GOOGLE_CLIENT_ID` empty (fine — login is skipped in dev) or origin not added to the OAuth client's Authorized JavaScript origins |
| No memory/XP/streak persistence | No database reachable — run via `docker compose up -d` (which supplies `DATABASE_URL` from the `db` service), or check `docker compose logs db` |
| A code change "works" but Render 500s on boot | Run `python -c "import app.main"` locally first — `ast`-level syntax checks miss real import/`NameError`s |
| Editing `test_client.html` white-screens the app | Single JS syntax error breaks the whole file — validate with `node --check` (extract the `<script>` block) before trusting a change |

---

For everything about *what* DuSu is and how each piece works (product, all 4 modes, DB schema, LLM chain, every frontend flow), see `CLAUDE.md` in repo root — this file only covers getting a fresh machine running it.

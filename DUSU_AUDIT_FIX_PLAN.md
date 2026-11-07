# DuSu - implementation plan + QA ledger for the 2026-10-30 product / UI audit

Source of truth for WHAT is wrong: `DUSU_PRODUCT_UI_AUDIT_2026-10-30.md` (evidence, screenshots, numbers). This file is HOW it gets fixed and HOW each fix is proven.
Owner's ask: *"act like a senior developer, make a plan, implement it, and like a QA check all and make sure all points are covered."*

## 0. Ground rules (what "done" means here)

1. **Nothing is committed, pushed or deployed by this work.** Everything lands in the working tree for review; the deploy question (this batch + the two earlier uncommitted batches) is the owner's. **Update 2026-10-31: the owner said "yes deploy" and the batch is live (7.7). Update 2026-11-07: the owner asked to push - it is committed on branch `fix/voice-screen-lock` and pushed to `origin` (see CLAUDE.md, top); nothing is merged into main.**
2. **Every audit item gets exactly one of five statuses** - never silently dropped:
   `DONE` (built + a check that fails without it) - `DONE*` (built, but a real device / the real world is the only full proof) - `PARTIAL` (the part that is safe to do now is done; the rest is named) - `OWNER` (needs a key, a decision, a store account or a phone that only the owner has) - `DEFERRED` (a deliberate later step, with the reason and the trigger).
3. **Risk order, not list order.** Server + measurement foundations first, then the first-run path, then Home / names, then the UI system, then the security sweep. Each train ends with its own tests AND a re-run of every suite it can have affected.
4. **A change I cannot measure in the lab is not shipped as "improved".** CDP throttling does not reach a service worker's own fetches, so the lab cannot prove a service-worker speed-up; that part is built conservatively and the real-phone proof is listed.
5. **Phone first, desktop untouched.** Desktop rules stay inside `@media (min-width:1200px)`; a new tablet rule lives in its own `768-1199` range; the phone column is changed ONLY where an audit item says so (memory: `dusu-desktop-ui-breakpoint`).
6. **Tests that pinned the OLD behaviour are updated in the same change and listed in section 6** - "fails by design" is never confused with "regressed".
7. **Honesty over polish in copy:** no invented plan entitlements, no "resets at" without evidence, no claim a feature does something it doesn't. Hindi lines are drafts in the house style (Devanagari + everyday English words in Latin, तुम, DuSu = she) and still need a native read.

## 1. Traceability matrix (updated as work lands - section 7 holds the evidence)

| ID | Audit item | Work package | Status | Proof (details in section 7) |
|---|---|---|---|---|
| P0-1 | Keys wall: 5 screens, "a minute" x4, English-only jargon, tiny "Get free key", level-check promise | WP3a | **DONE\*** | `verify K` (the wizard: above the fold, one paste box recognising the service, "Key 1 of 2", honest 5 minutes, Hindi, 360 / 1280) · `keys.spec` · mutant m06 · \* a native Hindi read + a real phone |
| P0-1b | "Taste first" (speak before any key) | - | OWNER | blocked by P0-4 (dead own keys) + a cost decision; design in section 5.2 |
| P0-1c | One key to start | - | OWNER | the 2-key rule is the owner's recorded decision (`MIN_VERIFIED_KEYS`, `MIN_KEYS`, `db.MIN_STORED_KEYS`) |
| P0-2 | No way to pay: stale plans page, no Free column, dead "Proceed" | WP6 + WP1b | **DONE\*** | `verify P` (Free column, honest "payment isn't open yet", outcomes true to `PLAN_LIMITS`, **Reserve my plan** stores plan + price opinion, idempotent, Hindi) · `tests/insights` · mutant m07 · \* the page can only collect interest - see P0-2b |
| P0-2b | Real payment (UPI / Razorpay) | - | OWNER | merchant account, prices, GST invoice, refund policy; then a checkout + webhook project |
| P0-3a | 1.7 MB logo on the first screen | WP2a | **DONE** | `verify W` (never requested) · `perf.cjs`: first visit 2,873 KB -> 425 KB |
| P0-3b | HTML has no cache validators; every launch re-downloads | WP1c + WP2b | **DONE** | `verify W` + `tests/insights` selftest (ETag / 304 on the front door AND every other door to the shell) · mutants M29 / M30 |
| P0-3c | Service worker network-first with no timeout | WP2b | **DONE\*** | `sw.spec` (3 s fallback to the cached shell, a 5xx is not shown over a good shell, no error body is ever cached) · \* CDP cannot throttle a service worker's own fetches, so the speed-up itself needs a real phone |
| P0-3d | Google Fonts = 2 extra origins; no offline fonts | WP2c | **DONE** | `verify W` (no Google request; fonts immutable for a year) · SIL OFL notice added · mutant m18 |
| P0-3e | Google sign-in script loaded for signed-in users | WP2d | **DONE** | `verify W` (loaded on the login screen only) |
| P0-3f | Split the 14.7k-line file | - | DEFERRED | its own project; re-measure after WP2 first (the first visit is now 425 KB, 315 KB of it the page) |
| P0-4 | DuSu's own Gemini / Groq keys unhealthy | - | OWNER | steps in section 5.1 (code cannot make a key) |
| P1-1 | Home overloaded (~20 blocks, 3,570 px, duplicates, footer) | WP4a | **DONE** | `verify H` · measured: Home 3,571 -> 1,699 px (a brand-new learner 3,548 -> 1,532) |
| P1-2 | One feature, many names | WP4b | **DONE** | `verify H` + `verify N` (retired names grep) |
| P1-3 | Three "start speaking" doors, no guidance | WP4c | **PARTIAL** | done: each Practice door named by outcome, the recommendation ("Start here") visible on phones, new-learner chips ("Where do I start?"); NOT done: a deterministic day-1 / 2 / 3 path - it needs the owner's product call on which door leads on which day |
| P1-4 | Empty states are dead ends | WP4d | **DONE** | `verify H` (Interview Reports, Grammar Coach x4 tabs, Practice Room; Career Path already had one) · mutant m16 |
| P1-5 | Rewards lecture + "Where we left off" for a brand-new learner | WP3b | **DONE** | `verify F` · mutants m01 / m02 / m17 |
| P1-6 | Red "Speaking Score 0 (-64)" after a 12 s chat; "Session saved." | WP3c | **DONE** | `verify F` · mutant m08 |
| P1-7 | "Connection error - Is the server running?" | WP3d | **DONE** | `verify O` (Face-to-Face, Daily, Learn, Hindi: plain words, and the tap the copy promises works) |
| P1-8 | Cold deep-link race ("isn't available") | WP3e | **DONE** | `verify R` (3 of 3 x 6 routes; a really-off feature is still refused; a hung /me lands on Home at 12 s) · mutants m03 / m13 - **my own first version stranded the learner on the sign-in card when /me hung; the check caught it and it is fixed** |
| P1-9 | Retention loops built but OFF | WP7 | OWNER | runbook in section 5.3; each step needs a real phone first |
| P1-10 | No product analytics | WP1a | **DONE** | `tests/insights` (unit 40 / scratch Postgres / WebSocket / 32 planted bugs) · `verify P / K` (the funnel sees the steps) · `verify U` (the owner SEES it on the dashboard, 7 / 30 / 90 days) |
| UI-1 | Old-style numerals ("o XP", "71" = "7I") | WP5a | **DONE** | `verify U`: ten digits drawn in the serif font are measured in pixels (spread 0.399 -> 0.034) · the two big timers that said only "tabular-nums" fixed · mutant m11 |
| UI-2 | Text too small, 36 font sizes | WP5b | **PARTIAL** | done: nothing under 12 px anywhere (0 of 34 screens x 2 phone widths; none declared in the source); six-step scale defined as variables. NOT done: the ~35 legacy sizes are not collapsed onto the six steps |
| UI-3 | Header = six items; oval avatar; dead female button | WP5c | **DONE** | `verify U` (4 widths, plus the Install switch ON at 360 and 320) · mutant m14 |
| UI-4 | Tap targets under 44 px | WP5c | **DONE** | `verify U`: every control on 34 screens at 390 and 360 px is >= 44 x 44 · mutant m12 · accepted: the desktop alias button (24 px, pointer), the repeat-weekday chips (40 x 44 so seven fit a 360 px row), three decorative arrow circles inside larger tappable cards |
| UI-5 | My Day header wraps; two add buttons; FAB covers row icons | WP5d | **DONE** | `verify U` (one row, one labelled add button, tabs in one language, all five tabs fit) |
| UI-6 | Three icon styles (SVG / emoji / mixed) | WP5e | **PARTIAL** | done: the More sheet (17 rows), the Practice / Home entries, My Day's check circles. NOT done: the long tail of in-content emoji (header bell / gear, status marks, tile decorations) |
| UI-7 | Brand colour drift | WP5e | **PARTIAL** | done: the report ring (gold -> indigo), `--gold` is an honest alias of `--accent`, all 17 old-brand gold glows / hairlines are accent tints. NOT done: ~100 raw hex / rgba values beside the tokens |
| UI-8 | "Sentences" tab cut; language pill behind the nav | WP5f | **DONE** | `verify U`: the pill is the first thing in the Home stack (visible at 360 / 390 / 768, Hindi too); Grammar Coach tabs whole at 390 / 360 / 320; My Day tabs fit · mutant m10 |
| UI-9 | Practice hub mixes two designs; recommendation hidden on mobile | WP5f | **DONE** | `verify H` |
| UI-10 | Desktop card widths; tablet header clipped | WP5f | **DONE** | `verify U` (the five Home cards are 420 px on desktop; the tablet header fits at 768 / 1024) |
| UI-11 | Locked badges only say "Locked" | WP5f | **DONE** | `verify U` (every locked badge has its requirement; every badge id has one) · mutant m15 |
| UI-12 | Ranks lists 0-XP accounts | WP5f + WP1d | **DONE** | `verify U` + `tests/insights` (a Ranks section) · mutant M31 |
| UI-13 | Journey: unlabeled chart, raw values, repeated quote | WP5f | **DONE** | `verify U` |
| UI-14 | Owner dashboard on phone: squeezed paragraphs | WP5f | **DONE** | `verify U` |
| C-1 | Interview role pre-filled "Frontend Developer" | WP4f | **DONE** | `verify H` |
| C-2 | Hindi register mixes aap / tum | WP4f | **DONE\*** | the Hindi the Home chat shows around DuSu's tum replies (orb hints, the headphones tip, thinking steps, limit lines) and the spoken Learn / Daily lines are all tum now (`verify H` checks the screen AND every line it can show) · mutant m27 · the parked Hindi of the old screens (Interview setup, Daily, Learn) stays as it is - unreachable, and the interview's is formal on purpose · \* a native read |
| C-3 | "8:30 PM" vs "7:00 pm"; "1 sessions" | WP4f | **DONE** | `verify H` · mutants m04 / m05 |
| C-4 | Footer "Modes (coming soon)", stale names | WP4a | **DONE** | `verify H` + `verify N` |
| C-5 | "DuSu keys / Mode - Personal or Office" | WP4f | **DONE** | `verify H` + `verify N` (no message anywhere - page or server - still points to "DuSu keys"; the 18 pointers said "More -> DuSu keys" after the row was renamed) · mutant m28 |
| C-6 | "Beta Testing - Unlimited" vs "free keys have limits" | WP4f | **DONE** | `verify H` |
| C-7 | New-learner chips mean nothing on day 1 | WP4f | **DONE** | `verify H` |
| C-8 | Hindi/English switch only changes new features (expectation) | WP4f | **DONE** | `verify H` / `U`: a one-line note on Home says what the button changes |
| C-9 | Roman vs Devanagari Hinglish per feature | WP9 | **DONE** | the written rule is in CLAUDE.md section 23 |
| A-1 | Secondary text 4.46:1 (< AA) | WP5g | **DONE** | `verify U`: 0 texts below AA on 34 screens at 2 widths (the old page: "78 XP to Speaker" at 4.46:1) |
| A-2 | Emoji-only mood buttons | WP5g | **DONE** | `verify U` |
| A-3 | Dark theme only; TalkBack / large font / iPhone not tested | - | OWNER / DEFERRED | needs devices; a light theme is its own project |
| E-1 | 148 `innerHTML` uses in old modules | WP8 | **DONE** | static scan of 137 sinks + the XSS canary on 18 screens + the Home chat + a model-written interview report (the same canary fails 20 of 21 on the old page) · mutant m09 |

## 2. Work packages

### WP0 - Baseline and tooling (S)
- Keep the audit's own numbers as the "before": copy `~/.cache/dusu-audit-shots/results-walk.json` to `results-walk-BEFORE.json`.
- `tests/audit/compare.py` diffs two result files (tiny text, small tap targets, contrast, overflow, per-screen scroll height).
- `tests/audit/verify.cjs` = assertion specs for the items below (PASS / FAIL, exit code), run with `tests/audit/spec.sh verify.cjs` against the scratch app that mirrors PRODUCTION's switches.
- `tests/audit/perf.cjs` = first-visit weight / request list of the login screen against the scratch app behind gzip (the live site cannot be measured until a deploy).

### WP1 - Server foundation (M)
- **1a analytics (P1-10)** - new package `backend/app/insights/` (models / service / api), same shape as `notify/` and `keys/`. Tables (new only, `create_all`, no ALTER): `ev_milestones (user_id, name, first_at; PK user_id+name)`, `ev_days (user_id, day; PK user_id+day)`. An ALLOW-LIST of event names (about ten); a milestone is written ONCE per learner (idempotent, in-memory dedupe so the hot path costs at most one write per process per learner). Server-side hooks (never trusts the client for what the server knows): `/me` -> active day; keys saved -> `key1_saved` / `key2_saved`; first spoken turn -> `first_sentence`; first persisted session -> `first_session`; plan reserved -> `plan_reserved`. Client beacons only for what only the client knows: `keys_seen`, `plans_seen`, `install_accepted`. `POST /ev {name}` (auth, allow-list, always 204, never an error to the learner), `GET /admin/funnel?days=` (owner only: learners per milestone, signups, D1 / D7 return, plan interest). Kill switch `settings.insights` (default on). Deleted with the account (`db.delete_user`, `admin_wipe_users`); `privacy.html` + `account-deletion.html` say what is stored. No text, no keys, no transcripts, no IP.
- **1b plan interest (P0-2)** - table `plan_interest (id, user_id, plan, price_feel, created_at; unique user+plan)`; `POST /plans/interest {plan, price_feel?}` (auth; plan in {starter, plus, pro}; an upsert, so tapping twice is one row), `GET /plans/interest` (the learner's own reservations, so the page can say "reserved"), the owner funnel shows counts per plan. Deleted with the account. No payment data of any kind.
- **1c cache validators (P0-3)** - `GET /` builds the page ONCE per file version (placeholders are constant per process), sends `ETag` + `Cache-Control: no-cache` and answers `If-None-Match` with 304 (today every open re-reads and re-sends 1.1 MB). `/assets/*` versioned files get `Cache-Control: public, max-age=31536000, immutable` (a changed asset needs a NEW file name - already the repo's rule for icons).
- **1d leaderboard (UI-12)** - only accounts with XP > 0 in the list and the podium; an honest empty state.

### WP2 - First-visit weight (P0-3) (M)
- **2a logo** - small WebP/PNG logo files (versioned names in `assets/icons/`), used by the login card and the header; `/logo.png` stays served (external references, Play listing) but the page and the service worker stop fetching it.
- **2b service worker** - `SHELL` no longer precaches the 1.7 MB logo; navigations stay NETWORK-FIRST (a deploy still shows immediately) but fall back to the cached shell after a 3 s timeout, and the late network answer still refreshes the cache. `CACHE` bumped. `sw.spec.cjs` (Node vm) pins the timeout, the fallback and the "never cache an error body" rule.
- **2c fonts** - the two families the page really uses (Cormorant Garamond 500/600/700, Inter 400/500/600; latin subset) are self-hosted from `assets/fonts/` with `font-display: swap`; the Google CSS + two preconnects are removed. The files are Google's own OFL woff2 (same bytes learners get today) so the lab and production render identically - which is what makes the numeral fix (WP5a) verifiable.
- **2d sign-in script** - `accounts.google.com/gsi/client` is injected only when the login screen is shown (and on 401 logout), not for every launch of a signed-in learner.
- **Deferred:** stale-while-revalidate for the shell + an "update ready" bar (needs a real-phone trace; see ground rule 4) and the file split.

### WP3 - First-run path (M-L)
- **3a Keys wall (P0-1)** - new order: one-line promise -> progress ("Key 1 of 2") -> ONE big "Get free key" button (Groq first) -> ONE paste box that recognises the provider from the prefix (`gsk_` Groq, `AIza` Gemini, `sk-or-` OpenRouter) -> the second key as two big provider buttons -> the guide and the videos BELOW, collapsed ("Need help? Watch how"). Honest time ("about 5 minutes, one time"), plain words ("free key from Groq" - the word "API" only in a footnote), bilingual (the wizard follows the learner's Hindi / English choice; Hindi default), the level-check promise only when the level check is ON (`/me.level_test`). The saved-keys management view (More -> My AI keys) is unchanged in behaviour. Acceptance: for a brand-new learner the first action is above the fold and the whole screen is at most two phone screens; the three-box form still works with the key engine OFF.
- **3b first-run overlays (P1-5)** - the four-card rewards sheet appears after the FIRST finished session (not before the learner has spoken); "Where we left off" is hidden until there is history (`next_hook` or a finished session).
- **3c short-session result (P1-6)** - a session under ~30 s / 2 turns shows "Too short to score - talk for about a minute to get a score." with no red delta; a Daily Talk with zero turns says "No sentences yet - say one to start" instead of "Session saved."
- **3d connection copy (P1-7)** - plain words in every language table ("No internet. Your chat is safe - check your connection") and a Retry where the screen has none.
- **3e deep-link race (P1-8)** - a route whose availability depends on a rollout flag waits for the first `/me` answer (with the existing 12 s ceiling) before it can conclude "isn't available".

### WP4 - Home, names, empty states, copy (L)
- **4a Home** - 8 practice tiles (Daily Talk, Face to Face Talk, Interview Prep, Learn, Practice Room, Job Interview Practice, Grammar Coach, My Day); Journey / League / Achievements / Career Path are reached from the nav tabs and More, not as tiles. The four feature banners that repeat a tile are hidden whenever the tile grid is showing; the "Your progress" nav-cards (duplicates of two tabs) and the website footer are removed (Privacy / Terms / Delete my data move to More); the keys card only appears when something needs attention. ONE "next step" card for a learner with no history ("Say your first sentence - Daily Talk, 2 minutes").
- **4b names** - one name per feature in nav, tile, screen title, report, Know About and the hub: *Daily Talk*, *Face to Face Talk*, *Learn*, *Interview Prep* (quick mock HR interview), *Job Interview Practice* (from your resume + a job), *Practice Room*. An inventory test greps the client and the registry for the retired variants.
- **4c three doors** - the Practice hub names each door by outcome and marks one recommended door on phones too (the desktop badge already exists); the Home "next step" card is the day-1/2/3 path.
- **4d empty states** - one helper (`emptyState`) = icon + one sentence + one primary button, used by Interview Reports, Grammar Coach tabs, Career Path, My interviews / resumes / job descriptions, Practice history.
- **4f copy** - role field = placeholder, not a value; "1 session"; one time format; "My AI keys" instead of "DuSu keys / Mode - Personal or Office"; the Beta badge says only what is true; new-learner chips ("Where do I start?", "Interview practice"); a one-line note on what the Hindi / English switch changes; the aap / tum strings that break the house rule.

### WP5 - UI system (L)
- **5a numerals (UI-1)** `font-variant-numeric: lining-nums tabular-nums` on the body, verified on the real self-hosted font file (OpenType `lnum` present) AND by rendering the "71" and "0 XP" cases.
- **5b type scale (UI-2)** a six-step scale as CSS variables; nothing under 12 px; the smallest labels move up and the screens are re-measured for overflow at 360 / 390 / 768 / 1280.
- **5c header + targets (UI-3, UI-4)** phone header = logo + install pill (when on) + one avatar button; the alias, name and sign-out live in Profile / More; the female button is removed; every control >= 44 x 44 (hit area extended where the visual stays small).
- **5d My Day (UI-5)** header on one row; the floating "+" removed in favour of the labelled Add button; the first tab label in the learner's language only.
- **5e icons + colour (UI-6, UI-7)** the More sheet, Home cards and the My Day checkbox glyphs move to the existing SVG set; the report ring uses the accent token; `--gold` gets a truthful alias (`--accent`) and the visible hard-coded gold / indigo values move to tokens. PARTIAL on purpose: the long tail of in-content emoji and raw colours is listed, not rewritten blind.
- **5f the rest (UI-8..UI-14)** shorter tab label; language pill placed in flow; one Practice hub pattern; a tablet range (768-1199) that stops clipping the header; badge requirements (accurate to the server rules); Ranks without 0-XP rows; Journey labels; owner dashboard stacked on phones.
- **5g accessibility (A-1, A-2)** `--ink-faint` lifted to >= 4.5:1 on every background it sits on; mood buttons named.

### WP6 - Plans and "Reserve my plan" (P0-2)
Plans page rewritten in outcomes using only what the code really enforces (`PLAN_LIMITS`: Starter 50, Plus 150, Pro unlimited AI replies a day; Free = your own free keys, with their provider limits), a Free column, an honest line that payment is not open yet, and a **Reserve my plan** button that stores interest (WP1b) and confirms ("Saved. We'll tell you the day payment opens."). "See plans" in every pop-up leads here.

### WP7 - Retention loops runbook (P1-9) (S)
A step-by-step owner runbook (section 5): the order (Install -> Notifications -> WhatsApp), the dashboard clicks, what to verify on a phone, what to watch afterwards (the new funnel + notification health), and the rollback of each.

### WP8 - `innerHTML` sweep (E-1) (M)
A static scan lists every `innerHTML` / `insertAdjacentHTML` / `outerHTML` site with interpolation; each is classified (constant / escaped / learner-controlled-unescaped). A browser canary seeds hostile text into every learner-controlled field (name, nickname, goal, role, topic, task titles ...) and walks the screens, failing if any markup or script runs. Real findings are fixed with `esc()`.

### WP9 - QA + docs
Section 4. CLAUDE.md gets one new section; memory notes updated.

## 3. Order of work (trains)

| Train | Contents | Exit gate |
|---|---|---|
| A | WP0 + WP1 + WP2 | insights / plans / cache unit + scratch-Postgres suites green; first-visit bytes measured; sw spec green |
| B | WP3 + WP6 | `verify.cjs` first-run + plans checks green; Keys + install + busy suites re-run |
| C | WP4 | Home measured (blocks, height); name inventory clean; Home / Know About suites re-run |
| D | WP5 | audit walk re-run: tiny text 0, small targets down, no overflow; screenshots reviewed |
| E | WP8 + WP9 | canary clean; every suite in section 4 green; independent review done |

## 4. QA strategy (what "checked" means)

1. **Per item:** a check that FAILS on the code before the change and passes after (the audit harness gives the "before" for free).
2. **Server:** pure unit tests, a scratch-Postgres suite through the real HTTP layer (idempotency, allow-list, isolation between two learners, deletion cascade, kill switch), and planted bugs (every one must be caught).
3. **Browser:** real Chromium against the real app on a scratch Postgres with PRODUCTION's switches (the audit harness) - new / keyed / active / lapsed / owner learners at 360 / 390 / 768 / 1280 px, English and Hindi; every changed screen photographed and looked at by me.
4. **Measured, not argued:** tiny-text count, tap-target count, contrast, overflow, Home height / block count, first-visit bytes and request count, before vs after.
5. **Regression:** every existing suite whose area a train touched (keys, voice-lock, my_day, notify, grammar, resume_interview, e2e) - results in section 7.
6. **Security:** the XSS canary (WP8) and the allow-list / IDOR checks on the new endpoints.
7. **Independent review:** a fresh agent reads the diff cold (not my conclusions) and each finding is reproduced or rejected.
8. **Not verifiable here (stated, not hidden):** real phones (TWA / PWA notch, microphone, TTS), real AI replies, real providers' wording, native Hindi quality, push delivery, TalkBack, large-font setting, iPhone Safari, the real Cloudflare path (first-visit timings on the live site can only be re-measured after a deploy with `tests/audit/live.sh`).

## 5. Owner-side items (code cannot do these)

**5.1 P0-4 - DuSu's own AI keys.** Gemini: make a new key from a Google project that HAS free-tier access (aistudio.google.com/apikey -> create the key in a NEW project) or set up billing, then put it in `backend/.env` `GEMINI_API_KEY`. Groq: a new free key at console.groq.com/keys -> `GROQ_API_KEY`. Then `docker compose up -d --no-deps backend`; `/health.server_keys` shows the truth within the hour (or at once after a restart). Until then "taste first" cannot be offered and the owner's own chats fail (honestly, with the pop-up).

**5.2 P0-1b - "taste first" (designed, not built).** A setting `taste_turns` (0 = off): a learner with no keys gets N free spoken turns on DuSu's chain (counted per learner in `memory.facts`, never refunded for a real answer), then the wizard appears with "you've had your taste". It needs the owner's cost decision (N, and whether the dead keys are healthy) - and it is the single biggest conversion lever the audit found. The new funnel (`/admin/funnel`, the dashboard's "First-run funnel" card) will show whether it moves "Saw the keys screen -> Saved a second key".

**5.3 P1-9 - the retention loops: a go-live runbook (each step on a real phone first, in this order).**
1. **Install + WhatsApp** (switch `install_mode`; dashboard -> Access -> "Install app + WhatsApp group").
   - Paste the WhatsApp invite in the box under the switch and Save (only `https://chat.whatsapp.com/<code>` or `https://whatsapp.com/channel/<code>` is accepted; tracking parameters are stripped). In WhatsApp: group settings -> "Send messages: only admins" and "Approve new participants: on" (members can see each other's phone numbers; a Channel hides them).
   - Set the switch to **Owner + early access**. On YOUR Android phone, in Chrome (a normal tab, not the Play app): the header shows an install button and More has "Install app" -> tap -> Chrome's own dialog -> Install. Open the new icon: full screen, no address bar, and the install button and More row are gone. iPhone: Safari -> Share -> Add to Home Screen (the sheet shows the three steps).
   - Proof it works: the dashboard funnel's "Installed the app" row counts you. Then **Everyone**. Rollback: Off (live within ~60 s).
2. **Notifications** (switch `notifications`; needs the Play App Signing fingerprint for the Play app).
   - Dashboard -> **Android app link**: add Play Console -> Setup -> App signing -> "App signing key certificate" SHA-256, then "Check with Google" (nobody but the owner can read it).
   - Set the switch to **Owner + early access**. On your phone - the installed web app AND the Play / sideloaded app - More -> Notifications -> Turn on -> allow -> **Send me a test notification** with the screen OFF: the line walks queued -> accepted by the push service -> reached this phone -> opened.
   - Proof: the dashboard's notification health (sent / accepted / arrived / opened in 24 h). A phone that never "arrives" is usually a battery saver or an OEM auto-start list. Then **Everyone**. Rollback: Off.
3. **WhatsApp announcement**: when the Play app is live, post its opt-in link in the group (the group is the channel for "this is new / the Play app is live / I have a problem").
Watch the first week on the dashboard: the funnel (7 / 30 / 90 days), the keys health block, the notification health. Each switch rolls back to Off within ~60 s.

**5.4 P0-1c - one key to start.** `MIN_VERIFIED_KEYS` (server), `MIN_KEYS` (client) and `db.MIN_STORED_KEYS` are one rule in three places; lowering it is a product decision (resilience vs friction). The funnel's "Saved a first key" vs "Saved a second key" rows measure what the second key costs.

**5.5 P0-2b - payment, and one inconsistency to settle first.** Merchant account (Razorpay / PayU), final prices, GST invoice, refund + cancellation policy, then a checkout + webhook project. Until then the plans page honestly says payment is not open and collects "Reserve my plan" (plan + an optional "too high / fair / great"), which the dashboard shows as demand and price feeling. **Settle before real plans exist:** `PLAN_LIMITS` in `main.py` says Free 500 / Starter 50 / Plus 150 / Pro unlimited AI replies a day - in the "quota" phase (DuSu's shared keys) the FREE tier would be allowed ten times more than the cheapest paid plan (the 500 is a "beta ceiling", the 20-day trial says 5 a day). Today's growth phase hides it (everyone is on their own keys, unlimited), and the plans page avoids a Free number on purpose; decide what Free means before the numbers on that page become a promise.

**5.6 P1-3 - the day-1 / 2 / 3 path.** Which door leads on which day (Home Start Speaking, Daily Talk, Face to Face Talk, Interview Prep) is a product decision; once it is made, the Home "today" card is the place for it.

**5.7 Native review** of every new Hindi line (they follow the house style - Devanagari with everyday English words in Latin, tum, DuSu = she - but are drafts), and of the Hindi register in the spoken Learn / Daily lines (C-2).

**5.8 Real-phone pass** (Android Chrome + the Play app, one iPhone): the notch / status bar, the new Keys wizard, the fonts, the header, the language pill, the keyboard over the wizard's paste box, TalkBack and the large-font setting (A-3).

**5.9 Deploy decision** for the whole uncommitted batch (the "AI busy" follow-ups + this work; production runs only the first AI-busy batch). Same procedure as every earlier deploy: rollback image tag, DB dump, tests on the BUILT image, live checks - this batch adds three new tables (`ev_milestones`, `ev_days`, `plan_interest`, created by `create_all`, no ALTER), an `insights` kill switch (default ON), and `sw.js` `dusu-v40`. **One item is a bug in production today:** the Keys card on Home retries a failing `GET /keys/status` in a tight loop (1,423 requests in 6 s were measured against the page as deployed, when the endpoint fails or the phone is offline); it is fixed in this batch, so waiting for the whole batch means living with it.

**5.10 Two XPs (found by the independent review).** `Progress.xp` (Journey lessons + Daily Talk) drives the all-time **Ranks** board and the Journey screen; `speaker_xp` (every speaking mode) drives Speaker Rank on Home and the **Weekly League**. A learner who only does Face to Face / Interview / Practice has Ranks XP 0, so they are not on the all-time board. This batch makes the Ranks copy honest ("Earn XP in a Daily Talk or a Journey lesson to join this board") and stops "has history" from depending on Journey XP; whether Ranks should count speaker XP is a product decision.

**5.11 - from the visual review (2026-10-31; details in 7.5b).**
- **"Starter" is two things.** The first XP rank on Home ("Starter - 85 XP to Speaker") and the cheapest paid plan ("Starter - Rs 299/mo") read as the same thing. Recommended: rename the RANK (e.g. "Beginner"; client `RANK_LABELS`, `rankLabel`'s fallback and the rewards text; server `life._RANK_LABELS`), because learners meet the rank first and the plans page cannot take payment yet; the plan ids (`starter` / `plus` / `pro`) stay as stored. Either rename is a branding call.
- **Devanagari headings** are drawn in the system's heavy sans next to the light serif Latin ("अपना plan चुनो"). A Devanagari serif is 100+ KB (against the weight work: 2.9 MB -> 0.43 MB); a lighter weight for Hindi headings is the cheap alternative.
- **The career screen says "Not set yet" while Journey shows "Your dream: ..."** (two fields). Prefilling the career box from the dream is one line in `renderProfile`; it was held back because a dream like "speak fluently" makes a poor career path.
- **Two decorative Grammar Coach settings.** "How much to show" (Auto / Gentle / Standard / Strict) and "Natural-English tips" (On / Off) are stored by `POST /gcoach/prefs` and read by nothing - the analysis and the screens ignore both. The Grammar plan promised strictness as a display cap by level (`verify.py` already has the caps; the preference would pick the level) and tips as the `natural` / `polish` marks. Wire them, or hide the two cards until then (the browser spec `grammar/browser/real.spec.cjs` clicks `#gcSetNat-off`).
- **`build_today` has the stale-counter bug too** (it reads the stored `sessions_today == 0`), so its "Keep your N-day streak alive" card practically never fires. `streak, sessions_today = _live_counters(prog)` there would make that card appear on Home every morning for anyone who practised yesterday - a visible change, so it is yours to approve.

## 6. Existing tests that pinned the old behaviour (changed in the same change - "fails by design" is never confused with "regressed")

| Test | What it used to expect | Now | Audit item |
|---|---|---|---|
| `tests/keys/browser/keys.spec.cjs` | a tester with healthy keys sees the Home card "Your AI keys" | the card appears only when something needs attention (the states that do are covered in its section E) | P1-1 |
| `tests/keys/browser/keys.spec.cjs` | a brand-new learner on Keys sees the three entry boxes, "Add two free keys", and "1 of the 2 working keys" | the first-run **wizard**: one Get-free-key button + ONE paste box, "Key 1 of 2" -> "Key 2 of 2"; the three-box screen is what a learner with keys (or a rollback) gets | P0-1 |
| `tests/keys/browser/keys.spec.cjs`, `install.spec.cjs`, `popup-look.cjs` | every sheet / pop-up control is at least 40 x 40 (and 40 high on the Keys screen) | 44 x 44 | UI-4 |
| `tests/keys/browser/static.spec.cjs` | the list of ids the key module creates at run time | the wizard's ids (`ksWiz`, `ksPaste`, ...) added, so the "no duplicate ids" check stays meaningful | P0-1 |
| `tests/keys/browser/sw.spec.cjs` | cache `dusu-v39`, the old SHELL | `dusu-v40`, the new SHELL (no 1.7 MB logo), and a new section: the 3 s fallback, a 5xx never shown over a good shell, an error body never cached | P0-3 |
| `tests/keys/unit.py`, `tests/keys/ws_selftest.py`, `tests/keys/browser/static.spec.cjs` | the real path to the keys is "More -> DuSu keys" (the server's fallback texts and 18 messages in the page said so) | "More -> My AI keys": the More row was renamed (C-5) and a learner following the old words found no such row - the messages, the server's texts and these three pins now say the real name | C-5 |
| `tests/audit/verify.cjs` section H (my own, earlier) | "about a dozen blocks or fewer" on Home | "no more than 15 blocks with every optional personal card showing" (the honest count; the height is the real metric and is checked too) | P1-1 |
| `tests/audit/verify.cjs` section H (my own, earlier) | "Start Speaking is above the viewport's bottom" (844 px) | still kept, and section U adds the stricter one: above the bottom NAV at 360x740, 390x800 and 768x1000 | P1-3 / UI-8 |
| `tests/keys/browser/oldnew.spec.cjs` ("old = old") | the page equals the page at the revision before the Keys work, except the Keys markup | **retired as a gate for this batch**: this batch deliberately changes Home, the header, names and CSS on every screen; the comparison to a fixed old page is replaced by `tests/audit` (`OLD_HTML` must make the new checks fail) | - |
| `tests/e2e/keys-tutorial.spec.ts` | both guide cards visible above the fold on the key screen | **not run here** (it needs a machine-global Playwright test runner that this box does not have); it drives the legacy / signed-out layout, which this work did not change; the first-run wizard moves the same two guides into a collapsed "Need help?" by design - update it if it is ever run against a signed-in first-run account | P0-1 |

Found by the final regression pass (every suite whose area this batch could touch, run against a frozen copy of the tree):

| Test | What happened | Verdict |
|---|---|---|
| `tests/notify/browser/real.spec.cjs` | "it names the time" wanted "7:00 pm"; the soft prompt now says "7:00 PM" | by design (C-3: one time style everywhere) - the pin is updated, 109 / 109 |
| `tests/resume_interview/browser/harness.cjs` `toHub` + `static.spec.cjs` | the whole Job Interview Practice real-browser spec crashed at its first click: Home no longer shows the banner card `#riHomeCard` when it draws the icon grid (P1-1) | by design - the helper now opens the hub through the card OR the tile (both open the same hub); 90 / 90 real + 243 + 164 looks + 170 x 2 flow + 210 edge + 123 xss + 65 coach + 22 device |
| `tests/resume_interview/parity_server.py` | "life._MODE_LABELS only gained the new mode" pinned the label "Face-to-Face" | by design (P1-2: "Face to Face Talk") - 86 / 87, the one left is the registry check that has failed since Grammar Coach added its Know About card (identical on the deployed code) |
| `tests/resume_interview/browser/static.spec.cjs` (3 checks) | "every CSS selector added for RI is ri-prefixed", "only a reduced-motion query and the desktop block", "sw.js cache bumped to dusu-v30" | **pre-existing**: they compare against the revision before Job Interview Practice and pin an old cache name, so they have failed since Grammar Coach / the later service-worker versions; they fail IDENTICALLY on the deployed code (`git archive HEAD`: 106 passed, 3 failed) - not touched |
| `tests/resume_interview/browser/edge.spec.cjs` (bare errors) | one check ("a server error is a generic sentence") failed once while the planted-bug run used the machine | a timing flake: the same spec passes alone, 210 / 210 |
| `tests/keys/parity.py`, `tests/resume_interview/parity_server.py`, `tests/grammar` unit tier | failed inside the frozen copy: it leaves out the `.head` baselines, and the Grammar Coach unit tier is not run through `run.sh` | run the documented way from the working tree: parity 52 / 52, Grammar Coach unit 1,233 + 1,946 + 199 + 102 + 218 + 338 = 4,036 |


## 7. Evidence and QA log

Everything below ran on scratch infrastructure only (a scratch Postgres on an internal Docker network with no route out, a fake model, fake keys, the real app, a real Chromium). The audit server mirrors PRODUCTION's rollout switches. Commands: `tests/audit/README.md`, `tests/insights/README.md`.

### 7.1 Measured, before -> after (the same measuring code on both pages)

| What | Before | After |
|---|---|---|
| Text under 12 px (127 screens: phone, small phone, desktop, Hindi, five kinds of learner) | 2,006 | 12 (hidden `font-size:0` labels) |
| Controls under 44 px (127 screens; lenient rule: a side under 40 px) | 570 | 34 (all the desktop header alias button - a pointer device) |
| Low-contrast text | 953 | 10 (emoji glyphs) |
| Controls with no accessible name | 7 | 0 |
| Screens that scroll sideways / console errors / failed requests | 0 / 0 / 0 | 0 / 0 / 0 |
| Home height, established learner | 3,571 px | 1,706 px |
| Home height, brand-new learner | 3,548 px | 1,603 px |
| Screens that got worse (`compare.py --screens`) | - | none |
| First visit, sign-in screen: transferred (lab, behind gzip) | 2,873 KB, 7 requests | 429 KB, 6 requests |
| ... largest contentful paint, unthrottled (median of 5 loads) | 0.27 s | 0.27 s |
| ... largest contentful paint on Slow 4G (median of 5 loads) | 8.7 s | 1.25 s |
| ... largest contentful paint on 3G (median of 5 loads) | 34.6 s | 4.4 s (page fully loaded: 34.6 s -> 9.5 s) |

The live Cloudflare path (tunnel time-to-first-byte) can only be re-measured after a deploy (`tests/audit/live.sh`). These are the medians of the closing run, after the last page edit. (An earlier five-load run read 1.8 s for the unthrottled "after" paint: that was the sign-in "taking a while" note appearing against the test's never-finishing stand-in for Google's script; the note now waits about 8 s and `verify W` pins that.)

### 7.2 The assertion suite - `tests/audit/verify.cjs` (13 sections, one check per fixed audit item; section Y = the visual-review fixes, 7.5b)

Sections: S smoke (no script error on 7 entry paths) - K first-run Keys wizard - R cold deep links - P plans + Reserve my plan - F first-run overlays + a short chat - O offline wording - H Home / names / hub / empty states / copy / Hindi Home chat - N static facts about the shipped page - U the UI system (numerals measured in pixels, type floor, header at 4 widths and with the Install switch on, 44 px targets on 34 screens at 2 widths, contrast, My Day, icons, tabs, badges, Ranks, Journey, owner dashboard incl. the funnel card, mood buttons, Hindi) - W first-visit weight - V pins from the independent review - X the XSS canary.

| Run | Result |
|---|---|
| Full run on the near-final page | 258 passed, 1 failed (S 7, K 33, R 8, P 18, F 10, O 7, H 43, N 14, U 71 + 1 failed, W 13, V 13, X 21). The one failure (five My Day tabs overflowed a 360 px row) was fixed and re-checked |
| Re-run of K + P + U on the final page | 123 passed, 0 failed (K 33, P 18, U 72) |
| Last full run on the final page | **259 passed, 0 failed** (see 7.2b) |
| Full run after the visual-review pass (2026-10-31) | **302 passed, 0 failed** in one run (S 7, K 33, R 8, P 18, F 11, O 7, H 43, N 14, U 73, W 13, V 13, Y 41, X 21). Section Y against the page as it was before those fixes (`OLD_HTML=.out/pre-vr.html`): 8 pass / 33 fail (the 8 are pins or server-side counters an HTML swap cannot undo). One earlier check was rewritten by design: UI-13 expected the stale "8 / 5 sessions today" of a learner who last practised yesterday; it now pins "0/5" and tests the "8 ✓ DAILY GOAL MET" wording by injection |
| The same sections against the page as it was BEFORE the fixes (`OLD_HTML`) | every section fails: S 1 pass / 6 fail, K 1 / 9, R 1 / 7, P crashed at its first missing element, F crashed, O 2 / 5, H crashed, N 2 / 12, U 2 / 12 then crashed, W 9 / 4 (the server-side half passes: the server is current), V 1 / 4, X 1 / 20 |

Reproductions that mattered: the retry loop of the keys card made **1,423 failed requests in 6 s** against the deployed page (1 after the fix); the service-worker checks added for review findings 4 and 5 failed 7 of 7 before the fix; the hung-/me deep-link check caught my own first version of the fix.

### 7.2b Last full run on the final page
**307 passed, 0 failed** on the final page (S 7, K 33, R 8, P 18, F 11, O 7, H 43, N 16, U 73, W 16, V 13, Y 41, X 21; it was 302 at the visual-review pass, +3 in W for the live findings of build 2, +2 in N for build 3), run against the code baked into the built image after the last page edit (2026-10-31; before the visual-review pass it was 259 with 12 sections: F 10, U 72, no Y).

### 7.3 Planted bugs ("does the suite notice?") - every one must be caught

| Suite | Bugs | Result |
|---|---|---|
| `tests/audit/mutants.sh` (client page, 47 entries incl. a control; m29-m47 are the visual-review fixes: 19 of 19 caught, and the control stays green) | history always true / never, deep-link wait removed, no hung-/me fallback, `plural`, time style, key-prefix map swapped, Reserve saves another plan, a short chat scored, an unescaped model string, the language pill back at the bottom, numerals back to old-style, 40 px My Day buttons, the alias back in the header, no badge hints, no empty-state button, rewards before speaking, a font from Google, no funnel card, the retry loop, history = Journey XP only, "No sentences yet" always, the wizard wiping a second key, an un-pressable saved opinion, a device-wide history flag, an "aap" hint on the Home chat, a pointer to a retired name | **27 of 27 caught + the control stays green** (two needed their TEST fixed first: a font mutant aimed at a font the page never loads, and the weight section ignoring the planted copy) |
| `tests/insights/mutants.sh` (server) | 38 (M33-M38: the live counters - yesterday's sessions shown as today's, a dead streak alive, the UTC day, `/me` raw, the Home chip raw, the dashboard raw - all six caught: four by the unit tier, two by the scratch-Postgres tier); the first 32: allow-list, memory, overwrites, erased opinions, cohort, Day-1, deletion, ETag, immutable cache, open funnel, a deep link without validators, the Ranks filter, `delete_user` forgetting the counters ... | 32 of 32 caught (M1-M30 earlier, M31 + M32 in this pass: both caught by the scratch-Postgres tier) |

### 7.4 The independent review (a fresh agent read the diff cold, nothing run; 9 findings, each reproduced or rejected before acting)

| # | Severity | Finding | Verdict and action |
|---|---|---|---|
| 1 | High | the Home keys card retried a failing `GET /keys/status` in a tight loop | CONFIRMED - **also in production today** (1,423 requests in 6 s against the deployed page). Fixed: a 30 s pause after a failure; the learner's own tap still asks. `verify V` + mutant m21 |
| 2 | Medium | "has history" and the Ranks hint used Journey XP, which Face to Face / Interview / Practice never raise | CONFIRMED - fixed (speaker XP, spoken sentences, the saved promise also count; honest Ranks hint); the two-XP question is plan 5.10 |
| 3 | Medium | "No sentences yet" shown after the learner spoke (slow result) | CONFIRMED - fixed (`Session saved.` when something was said) |
| 4 | Medium-low | the service worker stored /privacy, /terms, /account-deletion as the app shell and showed them in its place on a slow network | CONFIRMED by a failing-first spec - fixed |
| 5 | Low | the asset branch cached 502 / 503 answers for fonts and icons | CONFIRMED by a failing-first spec - fixed |
| 6 | Low | the key wizard wiped a second key pasted while the first was saving | CONFIRMED - fixed |
| 7 | Low | a saved price opinion could be un-pressed though the server never erases one | CONFIRMED - fixed (the chip stays pressed) |
| 8 | Low | the "had a session" flag was per device | CONFIRMED - fixed (per account) |
| 9 | Low | `--glass-brd` built with `color-mix()` (every border vanishes where unsupported); the plans page is Hindi without a toggle when the bilingual switch is off; Free 500 vs Starter 50 | the first: fixed (a plain rgba). The second: by design (the section-11 rule for new copy - Hinglish only when the switch is off). The third: a real product inconsistency - owner item 5.5 |

### 7.5 Regression pass - every suite whose area the batch could touch, run against a frozen copy of the tree

Server tiers (scratch Postgres): insights 40 / 133 / 11 - keys unit 234, selftest 174, WebSocket 126, parity 52 (from the working tree) - daily voice 22 + 125 - My Day 92 + 293 - Notifications 189 + 158 - Grammar Coach unit 4,036 (1,233 + 1,946 + 199 + 102 + 218 + 338), selftest 88, WebSocket 18 - Job Interview Practice unit 309, selftest 188, parity 86 / 87 (the one left fails identically on the deployed code).
Browser tiers (real Chromium -> real app -> scratch DB): keys 212, install + community + notifications 111, key pop-up look 83, static 92, service worker 62 - daily voice: Daily + Learn lock 166, other chats lock 343, "AI busy" 299 - My Day: repeating reminders 122, check / uncheck 137 - Notifications 109 - Grammar Coach 40 - Job Interview Practice: real 90, coach 65, flow 170 x 2, edge 210 x 2, device 22, xss 123, smoke 7, looks 243, looks (states) 164.
What failed and how each was settled is in section 6 (a changed pin, a flake that passes alone, three checks that fail identically on the deployed code).

**Regression pass after the visual-review fixes (2026-10-31), again against a frozen copy of the tree.** Server tiers (scratch Postgres): insights unit **50** / scratch-Postgres **139** / WebSocket 11 (the new counters: 10 + 6 checks) - keys unit 234, selftest 174, WebSocket 126, parity 52 (working tree) - daily voice 22 + 125 - My Day 92 + 293 - Notifications 189 + 158 - Grammar Coach unit 4,036 (1,233 + 1,946 + 199 + 102 + 218 + 338), selftest 88, WebSocket 18 - Job Interview Practice unit 309, selftest 188, parity 86 / 87 (the one left fails identically on the deployed code). Browser tiers: keys 212, install + community + notifications 111, key pop-up look 83, static 92, service worker 62 - daily voice: Daily + Learn lock 166, other chats lock 343, "AI busy" 299 - My Day check / uncheck 137 - Notifications 109 - Grammar Coach 40 - Job Interview Practice 90. **One failure, not from this work, now fixed in the test:** My Day's repeating-reminders spec (`real.spec.cjs`, 123 of 124) failed "the list has a Tomorrow group" when run at 03:00-03:20 India time - and failed **identically against the deployed production image `564de71cb4b0`**. A one-off probe showed the page is right (both groups, `TODAY` and `TOMORROW`, with their rings); the check was case-sensitive and the group heading is upper-cased by the CSS, so the word only matched in the daytime, when today's 09:00 ring has passed and a row chip says "Tomorrow". The match now ignores case: 124 of 124 at 03:30. `grammar/solo_gold.py` still prints one "wrong rule" line on a mistaken gold sentence (m010) - identical on the committed engine, which this pass does not touch.

### 7.5b The fresh-eyes visual review of the final screens (2026-10-31)

After the batch was finished, a fresh agent that had not seen any of the earlier work was given ~80 final screenshots (phone, small phone, desktop, Hindi; zoomed crops and pixel measurements) and asked only for defects a careful human would flag. It found no High defect and 20 findings. **Each one was checked against the screenshot and the code before acting** (a finding that was not a defect is listed as such), the real ones were fixed in the working tree, and every fix has a check that fails on the page as it was before (`verify.cjs` section Y, `OLD_HTML=.out/pre-vr.html`) plus a planted bug that the check must catch.

| # | Sev. | Finding | Verdict | What was done |
|---|---|---|---|---|
| 1 | M | Plans: "Reserve my plan" looks disabled and nothing says why | CONFIRMED (it is disabled until a plan is chosen; the 2.4:1 label is the disabled look) | a line above the button, "Tap a plan above to choose it" (gone once a plan is chosen, Hindi too), and a radio ring on each plan card that fills for the chosen one. **DONE** |
| 2 | M | "Starter" names both the XP rank and the paid plan | CONFIRMED | **OWNER**: rename the rank (recommended: "Beginner"; client `RANK_LABELS`, `life._RANK_LABELS`, the Know About / rewards text) or the plan. Not changed - both are the owner's brand words |
| 3 | M | XP numbers do not reconcile across Journey / Ranks / League | CONFIRMED (it is the "two XPs" of 5.10: Journey lesson XP vs Speaker XP; the weekly league counts the second) | **OWNER** (5.10). Not changed |
| 4 | M | My Day summary cut off ("Tasks, habits, goals & re...") | CONFIRMED | the line wraps to two lines at most; the header stays one row at 360 / 390, English and Hindi. **DONE** |
| 5 | M | Profile: the alias breaks mid-word ("BoldSparr / ow") | CONFIRMED (`.pf-email` carried `word-break: break-all` for the e-mail, and the alias line inherited it) | only the e-mail may break anywhere. **DONE** (390 / 360 / 320 px) |
| 6 | M | Journey "Who you're becoming": five equal bars, ISO dates broken in the middle, wrapping numbers | CONFIRMED | dates read "30 Oct" and never wrap; the chart is drawn only from 3 or more distinct days (one day of sessions is not "over time"); its label carries the numbers; "62 -> 64 (+2)" never wraps. **DONE** |
| 7 | M | "Your path: Not set yet" while Journey shows "Your dream: ..." | CONFIRMED (two separate fields: the onboarding dream and the career goal) | **PRODUCT**: prefill the career box from the dream (a one-line change in `renderProfile`) - held back because a dream such as "speak fluently" makes a poor career path. Not changed |
| 8 | M | Ranks: nothing for a learner not on the weekly board; "You are SharpCobra" beside the real name | CONFIRMED (the all-time board already pins an own row; the weekly league had none) | the league says "You're not on this week's board yet - Practise once and you're on it"; the subtitle reads "Others see you as <alias>". **DONE** |
| 9 | M (P) | A lapsed learner still sees "4 day streak" and "2/5 sessions today" | CONFIRMED - and it is **not only the lapsed**: `streak_days` and `sessions_today` only change when the learner next practises, so **every learner who practised yesterday saw yesterday's sessions as today's every morning**. Reproduced on the scratch server (`/me` for the 8-days-lapsed learner: 4 and 2) | `db._live_counters`: streak alive only if the last practice was today or yesterday (IST), sessions today = 0 on a new day; used by `/me`, the Home streak chip (`growth.streak`) and the owner dashboard. The stored numbers are untouched and the confidence composite still uses them. **DONE** (server; unit + scratch-Postgres + 6 planted bugs) |
| 10 | M-L | Hindi headings: heavy bold sans Devanagari next to a light serif Latin | CONFIRMED (the Latin is Cormorant Garamond; Devanagari falls back to the system sans) | **OWNER**: a Devanagari serif font costs 100+ KB against the weight work (2.9 MB -> 0.43 MB); a lighter weight for Hindi headings is the cheap alternative. Not changed |
| 11 | M-L | Practice hub: unequal cards; "Interview Prep" has a sliders icon that reads as Settings | PARTLY: the icon is real, the card styles differ by design (three guided modes with an eyebrow and a ring, three tools without) | Interview Prep now draws the briefcase Home uses. **DONE**; the card styles and the shared speech-bubble icon (nav "Daily" and Face to Face Talk) are noted |
| 12 | M-L | An empty session result looks like a loading state ("SESSION COMPLETE" over a ring of dots) | CONFIRMED (the ring kept its loading "...") | a dash in the ring, the title "Nothing to score yet" when nothing was said, and the loading ring / "Session complete" restored on the next result. **DONE** |
| 13 | L-M | Grammar settings: the delete label wraps to five lines; "Export" vs "Download"; unexplained options | CONFIRMED (+ a new finding, below) | the two data buttons stack full-width; the label is "Download my data" like My Day and Job Interview Practice; the "Counts only" explanation says what happens to the sentences. **DONE** |
| 13b | - | **NEW, found while triaging 13**: "How much to show" (Auto / Gentle / Standard / Strict) and "Natural-English tips" are saved but **nothing reads them** - the analysis and the screens ignore both | CONFIRMED (grep: only `service.py` stores them; the plan promised both) | **OWNER**: wire them (Gentle / Standard / Strict need a definition: the existing display caps by level are the natural hook) or hide the two cards until then. No explanatory text was added for them - it would describe a no-op |
| 14 | L-M | My AI keys: the dotted underline floats 20 px below "Get free key"; Remove looks like Change and Test | CONFIRMED | the underline hugs the words (a text decoration, not the bottom border of a 44 px box); Remove is tinted rose (the existing `.ky-del` rule was out-ranked). **DONE** |
| 15 | L | Header avatar initial nearly invisible (tan on periwinkle) | CONFIRMED (`.userchip span` out-ranked `.uav-init`) | dark initial, 5.6:1 at the centre of the gradient (was about 1.6:1). **DONE** |
| 16 | L | Home nits: language pill 3 px off the avatar; the mood row wraps 4 + 1; missions' circles and tracks near-invisible, no "0/30"; desktop chips wrap 3 + 1 | PARTLY | the mood row is five across (44 px+ targets at 360 / 390); the missions' empty circle and track are visible; **left**: the 3 px pill offset, the missions' figures, the desktop chip wrap (taste) |
| 17 | L | Hindi copy: space before the danda; 11 px helper text; unexplained chips; a garbled " - + " | MIXED | the danda has **no space in the source** (334 attached, 0 spaced; the gap is the glyph of Noto Sans Devanagari, measured: "करें।" = "करें" + "।" exactly) - **not a bug**; the 12 px floor holds (section U); the goals empty state is two clean sentences (English and Hindi); the Hindi priority chip "ज़्यादा" (more) reads "ज़रूरी" (important). **DONE** (a native speaker should still read all Hindi) |
| 18 | L | Achievements: two badges named "Consistent Speaker"; "DUSU" capitals | CONFIRMED | the hours badge is "Marathon Speaker (50+ hrs)" (client + `life.py`), the brand is spelled DuSu. **DONE**; the "(30 days)" repeated in a description is left |
| 19 | L | Spaced hyphen vs em dash; "Hi Asha, This week..." | the letter is the fake model's canned text; the dash is house style in the copy written in this batch | not changed |
| 20 | L (P) | Key wizard: opening "Need help?" shows only an arrow flip | CONFIRMED (the guide opens below the fold) | the tap scrolls the opened guide into view (instant under reduced motion). **DONE** |

Counts of the 20: **12 fixed outright** (1, 4, 5, 6, 8, 9, 12, 13, 14, 15, 18, 20), **3 fixed in their real part** (11, 16, 17 - the rest of each is a taste item or not a defect), **4 left to the owner / product** with a recommendation (2, 3, 7, 10), **1 taste item left** (19). One more owner finding came out of triaging 13 (13b, the two decorative Grammar settings), and finding 9 turned out to be a production bug, not a look.

### 7.6 Not verified (stated, not hidden)

A real phone or the Play app (notch / status bar, microphone, TTS, the keyboard over the wizard's paste box, TalkBack, the large-font setting, iPhone Safari); real AI replies and the providers' real wording; the live Cloudflare timings; push delivery; the native quality of every new Hindi line; light theme (not built). The service worker's speed-up cannot be shown in a lab: Chrome's network throttle does not reach a service worker's own fetches.

The visual review itself: it looked at screenshots from a Chromium with Noto Sans Devanagari, not at a handset; the Job Interview Practice "job" step was never photographed (the walk captured the resume step twice); the fresh page's mood row, the Journey chart with three or more days and the guide opening on the wizard were checked by measurement (section Y) and by looking at the scratch screenshots, not on a phone.

### 7.7 Deploy record, and what the live checks found (2026-10-31)

The owner said "yes deploy"; the batch is **live** (build 2, image `301a73d4ebf6`, 10:09 IST; build 1 `836d0b7fe4f9` ran 09:20-10:09). **Committed 2026-11-07 on branch `fix/voice-screen-lock` and pushed to `origin`; nothing is merged into main.** A third build (`d57621b7ea9f`) is tested and waits for the owner's go-ahead. Same procedure as every earlier deploy: a rollback image (`dusu-backend:pre-audit-fixes` = `564de71cb4b0`, `pre-etag-mime`, `pre-email-etag`), a database dump before each swap (`~/dusu-backups/dusu-before-audit-fixes-20261031-092022.sql.gz`, `dusu-before-etag-mime-20261031-100908.sql.gz`), the image built while the old container kept serving, then tested AS BUILT (112 / 112 files hash-identical to the tree, no `.env`, `import app.main` clean, every suite run against the code inside the image - `AUDIT_BACKEND=baked` is new), a health wait with an automatic rollback, and read-only live checks.

| Live finding | Cause | Status |
|---|---|---|
| Font + WebP logo served as `text/plain` | Starlette's fallback for an extension the slim image has no mime table for | **fixed in build 2** (`mimetypes.add_type`); Cloudflare still holds the old cached copies (a year, versioned names) - purging them is the owner's optional, cosmetic step |
| Repeat opens re-download the page (~385 KB); no ETag reaches the browser | Cloudflare's **Email Address Obfuscation** rewrites the one `mailto:` link in the page, injects a synchronous `email-decode.min.js` ahead of the app's script and drops the ETag because it changed the body | build 2: the ETag is weak (correct, but Cloudflare still drops it); **build 3: the address is assembled in `openHelp()`, never written in the markup - BUILT AND TESTED, NOT LIVE (waits for the owner)** |
| A synchronous Cloudflare script on every first visit | same cause | goes away with build 3 |
| PNG icons carry `max-age=14400` at the edge | the zone's own cache-header rewrite for PNGs | left (the origin sends `immutable`; harmless) |
| `busy.spec.cjs` E3 failed once in a long run | a test race: the "Working" chips can show from the last known status while the real check is still running; the sentence is claimed only afterwards | **test fixed** (E3 waits; E3b pins the order; planted bug Y24 caught); the page was right |

Live measurement (`tests/audit/live.sh`, throttled, before build 3): first visit ~0.66 MB (page ~385 KB, Google's sign-in script ~112 KB, fonts ~139 KB, images ~25 KB). **Google's sign-in button renders on the live page** (`tests/audit/live_gis.cjs`, control run on the old page first). Not measurable here: the service worker's own fetch (CDP throttling does not reach it), so the repeat-open saving is measured with a conditional `curl` after build 3.

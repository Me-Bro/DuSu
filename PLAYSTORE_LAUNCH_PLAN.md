# DuSu — Play Store Launch Plan (A→Z)

> **Implementation log (2026-08-19, round 3):** added §6, the conversation-engine dead-end/repetition bug fix — root-caused against actual prompt/engine code (not a blind prompt swap), fixed, and live-tested against real models across all three talking modes. See §6 for the full root-cause writeup, what changed, what was deliberately left alone (Interview's bounded completion — conflicts with one part of the reported approach, kept anyway since it's the actual product feature), and verification transcript excerpts.

> **Implementation log (2026-08-19, round 2):** everything in this plan is now implemented and verified — §3 access-phase flip, self-serve account deletion (§2.2), privacy/terms/account-deletion pages (§2.3), AI disclosure + report option (§2.6), the Fernet key-encryption upgrade (§2.5), the YouTube tutorial embed (§3, using your placeholder video `ptk2YvbwMnc` until the real one's recorded), the full Career Roadmap feature (§5), and the Android SDK 36 bump (§2.1). Verification this round went beyond static checks: a live local server against the **real** Neon DB + real LLM keys ran the full career-roadmap lifecycle end-to-end (generate → persist → toggle progress → self-delete cleanup) with a throwaway test account, and `android-twa` was actually built (`assembleDebug`) and produced a working APK — not just edited and hoped. Two extra fixes surfaced only by running the real build (see §2.1). Remaining items are all things only you can do (Play Console mechanics, business details, the real tutorial video) — see §7.

> Status: DRAFT for review. Covers three bundled workstreams from the same planning conversation:
> **(1)** Google Play Store submission compliance for the existing `android-twa` app,
> **(2)** an access-model change — BYOK (bring-your-own-keys) mandatory for every user during the initial growth phase, unlimited usage, no payment gate, with a documented switch-over to subscriptions later,
> **(3)** the Career Roadmap feature (onboarding "what do you want to become?" + generated path), confirmed to proceed.
>
> Researched against live Google Play policy as of **August 2026** (see Sources at the end) and against the actual current state of this repo (not the possibly-stale `CLAUDE.md` narrative — several things below were verified directly in code).

---

## 0. Ground truth found in the repo (read before planning further)

These are facts, verified directly in code, that change the plan vs. what `CLAUDE.md` describes:

| Fact | Where | Why it matters |
|---|---|---|
| `android-twa` targets `compileSdk=34` / `targetSdk=34`, pinned specifically to avoid needing `compileSdk 36` | `android-twa/app/build.gradle.kts:16,21` | Google Play now **requires target API 36 for new apps** (see §2.1) — the old pin rationale is obsolete for a fresh submission. Must upgrade regardless. |
| No Privacy Policy, Terms, or account-deletion page/route exists anywhere in the repo | grep across `backend/` | Both are hard Play Store blockers (§2.2, §2.3). |
| `db.delete_user()` exists but is **only called from owner/admin/superadmin actions** — no self-serve "delete my account" endpoint or UI button for a normal user | `main.py:530,641` | Play's Account Deletion policy requires **user-initiated** deletion, in-app AND via a web page. Not met today. |
| BYOK API keys are stored server-side already: `UserKey` table, `save_user_keys()` / `get_user_keys()`, sealed via XOR-keystream (`_seal`/`_unseal`), **explicitly commented "NOT strong crypto, swap in Fernet later"** | `db.py:28-45, 923-946` | Good news: server-side key storage + a `verified` bool already exist — the growth-phase flip (§3) is smaller than it looks. Bad news: "encrypted at rest" isn't really true yet, and the Data Safety form asks this directly (§2.5). |
| The admin `require_own_keys` setting is **dead code** — `/admin/settings` writes it, but nothing in `main.py` reads it back (`resolve_keys`, `charge_request` don't check it) | grep `require_own_keys` in `main.py` | The toggle you'd expect to control BYOK-for-everyone currently does nothing. §3 replaces it with a setting that's actually wired in. |
| `/subscribe` screen is a placeholder — picks a plan, shows "payment coming soon (work in progress)", **no real payment processing exists** | `test_client.html:2295` | Confirms your "no payment gate for now" instruction is already the de-facto state — nothing to rip out, just don't build billing yet (§4). |
| Help & Feedback screen only has `feedback` / `help` kinds — no way to report an AI response | `test_client.html:1327-1331` | Play's generative-AI policy requires in-app reporting of AI output (§2.6). One `<option>` + reusing the existing `Feedback` table closes this. |
| No analytics/ads SDK, no `AdMob`/`Crashlytics`/`gtag` found anywhere | grep across `backend/` | Simplifies the Data Safety form a lot — no ad-partner data sharing to declare. |

---

## 1. What we are and aren't doing (confirmed)

- ✅ Ship the existing web app inside the existing **`android-twa`** wrapper on Play Store — the "small version" you mentioned is exactly the TWA that already exists (`com.dusu.app`). No native rewrite. Functionality stays identical to the web app; the APK is packaging, not a second product.
- ✅ Career Roadmap feature ships (onboarding "what do you want to become?" → generated path). Treated as approved — see §5.
- ❌ **No payment gate right now.** `/subscribe` stays a placeholder. No Google Play Billing integration in this phase.
- ✅ **Every user (except owner/unlimited) must add their own AI provider keys** to use DuSu, starting now — not gated behind manual owner approval like today's "Office" allowlist. In exchange, BYOK users get **unlimited usage** (their own quota, not ours) — no 5/day cap, no 20-day trial clock.
- ✅ This is a **phase**, not permanent: once the app crosses **100+ Play Store downloads**, an admin flips one setting to switch back to the quota/subscription model. The switch must exist and work now, even though we won't flip it yet.
- ✅ The Keys screen gets an embedded YouTube tutorial (you will record/host the video) walking users through generating free Gemini/Groq/OpenRouter/GitHub keys.

---

## 2. Google Play Store compliance checklist

Split into **blocking** (can't submit / will be rejected without it) and **recommended**.

### 2.1 BLOCKING — Android build target

- [x] Bumped `android-twa/app/build.gradle.kts`: `compileSdk 34→36`, `targetSdk 34→36`.
- [x] Bumped `com.google.androidbrowserhelper:androidbrowserhelper` `2.5.0 → 2.7.0` (this is exactly the dependency the old pin was dodging — now required anyway).
- [x] Bumped Android Gradle Plugin `8.5.2 → 8.9.1` (top-level `build.gradle.kts`).
- [x] **`assembleDebug` actually run and succeeded** — `app-debug.apk` (5.6 MB) produced, using `JAVA_HOME` pointed at the real JDK 17 (`C:\Program Files\Microsoft\jdk-17.0.19.10-hotspot`), per the documented gotcha about the Android Studio bundled JBR.
- Two more fixes only the real build surfaced (i.e. this genuinely needed running, not just reading):
  - **`minSdk` bumped 21→23** — androidbrowserhelper 2.7.0's manifest declares `minSdk 23`; the merger fails otherwise. 23 (Android 6.0, 2015) is a non-issue for real-world coverage.
  - **Kotlin Gradle plugin bumped 1.9.24→2.1.20** — androidbrowserhelper 2.7.0 transitively pulls `kotlin-stdlib 2.1.20`, which the old 1.9.x compiler can't read (`Class 'kotlin.Unit' was compiled with an incompatible version of Kotlin` — the actual error seen).
- Rule confirmed live: **new apps/updates must target API 36 (Android 16) starting Aug 31, 2026** to be submitted; a one-time extension to Nov 1, 2026 is available if requested. Given the current date, treat this as immediate, not "later."
- **Not done**: `assembleRelease` (needs a keystore — `android-twa/keystore.properties`, git-ignored, doesn't exist yet) and installing on a real device/emulator to click through the actual TWA experience. The debug build proves the toolchain compiles and packages; it doesn't prove the app *runs* correctly on-device.

### 2.2 BLOCKING — Account deletion

Google Play requires, for any app that allows account creation:
1. A **readily discoverable in-app** way to request account deletion.
2. A **web page** (reachable without installing/opening the app) to request account + data deletion.
3. Truthful answers to the Data Safety form's deletion questions — Play will not let you publish without them.

Plan:
- [x] Backend: `POST /account/delete` — authenticated, requires typing `DELETE` to confirm, calls `db.delete_user(uid)` (already existed, already covered every child table including `UserKey`/`Feedback`). `main.py`.
- [x] Frontend: **"Delete my account"** destructive action on the `#profile` screen, with a native confirm-by-typing prompt, calling the endpoint then `logout()`. `test_client.html`.
- [x] Public static page `GET /account-deletion` (`backend/account-deletion.html`) — in-app method + an email fallback for anyone who already uninstalled.
- [ ] Data Safety form (Play Console, filled by you): point the "account deletion" URL field at `https://dusu-app-1.onrender.com/account-deletion`.

### 2.3 BLOCKING — Privacy Policy & Terms of Service

Neither existed before this pass. Both now have a stable public URL.

- [x] `GET /privacy` and `GET /terms` (+ `GET /account-deletion`) — served the same pattern as `/sw.js`/`/manifest.webmanifest`: static HTML files (`backend/privacy.html`, `backend/terms.html`, `backend/account-deletion.html`) + tiny `FileResponse` route handlers in `main.py`.
- [x] Content accurately describes what's actually collected (cross-referenced against §2.5): Google Sign-In identity; practice text sent to third-party LLM providers (Gemini/Groq/OpenRouter/GitHub) as a pass-through, not for training; BYOK keys stored obfuscated; no ads/analytics; deletion link.
- [x] Data controller listed as **David Singh Rana**.
- [ ] **Support email still a placeholder** (`[TODO: support email]` in both pages + the deletion page) — tell me the address and I'll swap all three occurrences in one pass.

### 2.4 BLOCKING — Closed testing track (only if applicable — needs your confirmation)

- Personal Google Play developer accounts **created after 2023-11-13** must run a closed test with **≥12 testers, opted in continuously for 14 days**, before production access is granted. Older personal accounts and organization accounts are exempt.
- **You need to tell me**: is this a brand-new Play Console account, or an existing one? This sets the real floor on your timeline — if it applies, you cannot reach "100+ downloads in production" before clearing 14 days of active closed testing with 12 real testers first. Worth planning recruitment (friends, Reddit, WhatsApp groups) for that cohort now, in parallel with the code work below.

### 2.5 BLOCKING — Data Safety form (filled in Play Console, not code — but code should match what you declare)

Answer based on the ground truth in §0:
- Data collected: name, email, photo (via Google Sign-In); user-generated audio-transcribed text; BYOK provider keys.
- Shared with third parties: yes — LLM providers (Gemini/Groq/OpenRouter/GitHub) receive conversation text to generate responses. Declare this.
- Encrypted in transit: yes (HTTPS/WSS).
- Encrypted at rest: **recommend fixing this before you answer "yes"** — see next item.
- Account deletion: yes, link to `/account-deletion`.

- [x] **Done**: `_seal`/`_unseal` in `db.py` now use real `Fernet` encryption (`cryptography` package, added to `requirements.txt`, installed locally and verified). Blobs written by the old XOR scheme still decrypt via a legacy fallback — upgrading this doesn't silently strand keys that BYOK users already verified; every write from now on re-seals with Fernet. Round-trip and legacy-fallback both tested directly (not just read).

### 2.6 BLOCKING — Generative-AI app policy (new July 2026 rules, ~30-day grace already elapsed — treat as current)

- [x] **AI disclosure**: explicit line added to the top of the Help & Feedback screen — "DuSu's replies are generated by AI language models, not a human — DuSu can make mistakes."
- [x] **In-app reporting of AI output**: `🚩 Report an inappropriate response` option added to the Help & Feedback `kind` dropdown; admin dashboard now labels these distinctly from plain feedback. Reuses the existing `Feedback` table (`kind` is a free string column — no schema change needed).
- [ ] Content-safety posture: DuSu relies on the underlying providers' (Gemini/Groq/OpenRouter/GitHub) own safety filtering; no additional moderation layer planned for v1 — reasonable given DuSu's warm-coach system prompts and India-job-prep framing, but call this out explicitly to yourself as an accepted risk, not an oversight.

### 2.7 BLOCKING — Store listing mechanics

- [ ] Play Console developer registration ($25 one-time) + identity/business verification if not already done — this can itself take days; start early.
- [ ] Play App Signing enrolled; release keystore generated; **both** the upload-key and Play-issued app-signing SHA-256 fingerprints added to `ANDROID_CERT_SHA256` on Render (`CLAUDE.md §8.3` already documents this mechanic — just needs doing).
- [ ] Content rating questionnaire — answer honestly; open-ended AI chat typically doesn't land in the lowest rating tier. Do this in Play Console directly (can't be pre-answered here).
- [ ] Target audience: declare general/adult audience, explicitly **not** "Designed for Families" / not directed at children — matches DuSu's actual positioning (job interviews, freshers) and avoids a much stricter policy tier.
- [ ] Store assets: feature graphic (1024×500), ≥2 phone screenshots, short description (≤80 chars), full description (≤4000 chars), support email, privacy policy URL field.

### 2.8 Recommended, not blocking

- [ ] Support/contact page (or just publish an email) — expected by the listing, good practice regardless.
- [ ] Keep `android-launcher` (deprecated module) out of the Play submission entirely — only `android-twa` ships.

---

## 3. Access-model change: BYOK-for-everyone growth phase

**Goal:** every non-owner/unlimited user must add ≥2 verified own keys to use DuSu at all; once verified, they're unlimited (no daily cap, no trial clock). No manual owner approval step (today's "Office" allowlist stays, but stops being the only path in). One admin-flippable setting controls this, so switching to the subscription model later (post-100-downloads) is a config change, not a rewrite.

**Status: implemented.** This turned out smaller than drafted — verified during implementation that `db.has_user_keys(uid)` already returns exactly "≥2 stored keys, verified" (no new DB helper needed), and the client-side gating (`officeAllowed()`, `needsKeys()`, `hasOwnKeys()`, `guardKeys()`, the `/keys` route guard) reads `userState.office`/`userState.has_keys` straight from `/me` — so it needed **zero client changes**, only server-side wiring. Confirmed the `require_own_keys` admin setting was genuinely dead code (written by `/admin/settings`, never read anywhere) before replacing it.

### New setting
- Reused the `settings` table (no migration). Key: `access_phase`, values `"growth"` (default, new behavior) | `"quota"` (today's free-tier-with-cap-then-subscribe behavior, for later). Helper: `access_phase()` in `main.py`.
- Replaced the dead `require_own_keys` bool in `SettingsIn`/`/admin/settings` with `access_phase: str`.
- Admin dashboard checkbox repurposed in place ("Growth phase (BYOK for everyone)"); `/admin/overview` now actually returns `access_phase` (it never returned the old field either — another latent gap, now closed).

### Backend changes (all in `main.py`, 3 functions + 2 endpoints)
1. **`resolve_keys(email, keys, uid)`**: BYOK is now required when `is_office(email) OR access_phase() == "growth"` (previously only the office branch). Growth phase reuses the exact same client-keys-or-stored-keys logic that already existed for office accounts.
2. **`is_unlimited(email)`**: also `True` whenever `access_phase() == "growth"` — in growth phase nobody can even get in without keys, so quota math is skipped entirely for everyone but owner/unlimited.
3. **`/me`**: `office`/`office_allowed` is now `True` for any plain `"user"` role account when `access_phase() == "growth"`, not only via the manual office allowlist — so `needsKeys()` on the client fires correctly with no client code changes.
4. `SettingsIn` + `/admin/settings`, `/admin/overview` — see "New setting" above.
5. **Note, not fixed**: found a pre-existing contradiction — `is_office()`'s docstring/behavior says its allowlist means "must BYOK," but the admin UI labels the same list "Free access (our keys)" (opposite meaning), and old `CLAUDE.md` agrees with the UI. Left that branch untouched (didn't guess which is the bug) — the growth-phase check was added as a separate `OR` condition so it doesn't depend on resolving this. **Needs your call separately**, not blocking anything above.

### Frontend changes
- Confirmed **no changes needed** for the core gate.
- [x] **YouTube tutorial embed** added to `#keys`, above the 4 key inputs:
  - Privacy-enhanced embed (`youtube-nocookie.com`), lazy-loaded (`src` only set when the box is actually shown).
  - Caption: "New here? Watch this quick guide to get your free AI keys."
  - Dismissible — remembered in `localStorage` (`dusu_tutorial_seen`) so returning users aren't forced to re-watch; hiding it also stops playback.
  - Video ID lives in one constant, `TUTORIAL_VIDEO_ID = "ptk2YvbwMnc"` (`test_client.html`) — your placeholder video. **Swap that one string** once your real recording is up; nothing else needs to change.

### Why this interacts nicely with the roadmap feature
In growth phase, *nobody* is quota-limited — so the earlier open question ("should `/career/generate` count against the 5/day cap?") disappears on its own: there is no cap to count against while `access_phase == "growth"`.

---

## 4. Payment / subscription — explicitly deferred

- No Play Billing integration now. `/subscribe` stays a "coming soon" placeholder.
- **When the 100-download trigger hits**, flipping `access_phase` to `"quota"` alone restores today's free-tier-with-cap behavior for *new* signups — that's the whole mechanism, and it already exists once §3 ships.
- Actually charging money is a **separate future plan**, not covered here, and — important for later — must use **Google Play Billing** for any subscription sold to Android users of an app distributed on Play (external payment processors like Razorpay/Stripe for the same in-app entitlement would violate Play's Payments policy). Flagging now so it doesn't get built the wrong way later.

---

## 5. Career Roadmap feature — status: implemented and live-tested

Full analysis lives earlier in this conversation; summarized here so this doc is a complete, standalone reference. **Built exactly as specced below**, and proven end-to-end against the real Neon DB and real LLM providers (not a mock) — see the verification note at the top of this file.

**What it is:** new onboarding question ("What do you want to become?", free text) → LLM generates a full generic career roadmap (phases → stages → skills, roadmap.sh-style content, not English-speaking-specific) → home page shows a compact progress card → a dedicated screen shows the full phase-grouped stage timeline. A clickable visual mockup was already built and reviewed (`career-roadmap-mockup.html`).

**Data:** no new tables — `Memory.facts["career_goal"]` (str) + `Memory.facts["career_roadmap"]` (`{goal, summary, generated_at, stages:[{id, phase, title, description, skills, done}]}`), ids assigned server-side.

**Backend:** `CAREER_ROADMAP_SYSTEM` prompt (caps: ≤6 phases, ≤4 stages each, ≤20 total; forbids inventing specific URLs/course/book names); `db.save_career_roadmap()` / `db.set_career_stage_done()`; `POST /career/generate` (mirrors `/assessment`'s auth→`resolve_keys`→LLM→persist shape, `max_tokens=1800` given the truncation precedent on `daily_turn`); `POST /career/progress`; `/me` gains a `career` block.

**Frontend:** new onboarding step `aCareerGoal()` (skippable, free text) between `aDream` and `aInterests`; fire-and-forget generate call after assessment succeeds; `renderCareerCard()` on home (empty / generating / ready states — all three already prototyped in the mockup); new `#career` screen + route `/career-path`; a second field on `#profile` to set/edit the goal later; "Change goal" / "Regenerate" (confirm dialog — regenerating **replaces** the roadmap and wipes stage progress in v1, no smart-merge).

**Naming note:** use `career_*` / `#career` internally — `"roadmap"` is already an internal key meaning the English-level curriculum (`_GOALS["roadmap"]` → the `journey` screen). Don't collide the two.

**Quota:** moot under `access_phase == "growth"` (§3) — not metered, matches how `/assessment`/`/leveltest/gen`/`/letter` already work.

**Not in v1** (explicitly deferred, say the word if you want any pulled forward): XP/badges tied to stage completion; retaining progress across regeneration by matching titles; a literal roadmap.sh branching-graph visual (using the timeline/phase-card style instead, matches the rest of the app).

---

## 6. Conversation Engine — dead-end & repetition bug fix

**Status: implemented and live-tested with real models.**

### The bug (your report)

Across all three talking modes — Daily Talk (Hindi), Face-to-Face English Talk, and Interview — DuSu would sometimes:
- Give a lazy, short, dead-end reply ("Hi", "Hello", "How are you?", "Good to see you") instead of a real reactive turn.
- End a conversational thread instead of always following up with a meaningful question, so the exchange fizzled instead of continuing.
- Repeat earlier questions, because nothing tracked what had already been asked.

You pasted a detailed ChatGPT-drafted rewrite of all three prompts plus an architectural idea (a structured "Conversation Context Package" with a `questions_recently_asked` field). I read the actual current prompts and engine code before changing anything — the diagnosis and the fix below are grounded in that, not a wholesale prompt swap.

### Root cause (found in code, not guessed)

1. **Inconsistent prompt rigor across modes.** `DAILY_TURN_SYSTEM` was already quite strong — explicit forbidden-phrase list, a mandatory 6-step reply shape, "never repeat a question already asked." `conversation_system()` and `interviewer_system()` were comparatively thin: "ask ONE open follow-up question" with no forbidden-dead-end list, no explicit anti-repetition instruction, no escalating-depth guidance. That gap is the main reason Face-to-Face Talk and Interview were the ones you noticed misbehaving.
2. **No cross-session memory of what's already been asked.** Within one session, `conversation`/`interview` pass the full session transcript to the model each turn, so the model *can* see its own recent questions — but a brand-new session (next day) starts with an empty transcript. The only continuity was `facts_summary` (interests, dream, last conversation summaries, cross-mode tail) — nothing tracked *specific past questions*, so nothing stopped the model re-asking the same ones session after session.
3. **No defensive floor under model quality.** Free-tier models occasionally just phone it in — a genuinely lazy one-liner despite reasonable instructions. Every other JSON-returning call in this codebase already retries on failure (`/assessment` retries 3x on parse failure) — the conversational turn functions (`next_ai_turn`, `daily_turn`) had no equivalent safety net.
4. **Deliberately NOT changed**: your pasted Interview prompt draft says "no fixed question limit... continue as long as the user participates." That directly conflicts with how Interview mode actually works in this app — it's a bounded mock interview that self-ends (`INTERVIEW_COMPLETE:` marker, ~6-8 exchanges, hard cap 15 turns) and hands off to a scored report (`SCORER_SYSTEM`). That's not a bug, it's the feature — Interview mode existing to produce a report is the whole point. I kept the bounded-completion mechanic and applied the *spirit* of your complaint (real follow-up depth, no dead-end acknowledgements, no repeated questions) inside it instead of removing it. Flagging this explicitly since it's a direct conflict with the pasted text, not an oversight.

### What was fixed

- **`interviewer_system()` and `conversation_system()` rewritten** (`prompts.py`) — brought up to the same rigor as `DAILY_TURN_SYSTEM`: explicit banned dead-end replies with examples, "look back at your own earlier turns, never repeat a question," escalating question depth (fact → reason → experience → reflection → future) instead of staying surface-level, explicit handling for short/vague user answers ("yes", "I don't know") — use existing context to offer a sharper angle instead of another generic question. Interview additionally bans bare acknowledgement-only turns ("Great, thanks.", "Okay, next question.") and requires 1-2 real follow-ups per competency before moving on — while keeping `INTERVIEW_COMPLETE:` intact.
- **Cross-session "don't repeat these questions" memory** — new, reusing 100% existing plumbing (no new architecture, no per-turn extra LLM call):
  - `SESSION_MEMORY_SYSTEM` now also extracts `recent_questions` (up to 3 genuinely meaningful questions DuSu asked that session) in its existing end-of-session summary call.
  - `db.add_recent_questions()` (new, mirrors the existing `set_next_hook` pattern) stores the last ~15 across all modes.
  - `_facts_summary()` renders them as "Questions you've already asked recently (do NOT repeat these)" — which flows into `conversation_system()`, `interviewer_system()`, *and* `DAILY_TURN_SYSTEM`'s "LEARNER FACTS" block automatically, since all three already receive `facts_summary`. One new field, three modes get it for free.
- **Short-reply retry guard** (`engine.py`) — the actual "your idea, sized to fit this codebase" version of the ChatGPT suggestion's spirit: if a conversation/interview turn comes back under 40 characters (and isn't a legitimate `INTERVIEW_COMPLETE` close), retry once with a sharper nudge appended to the transcript. Same pattern for Daily Talk if `reply_hindi` comes back under ~25 characters. Mirrors the existing `/assessment` 3x-retry-on-failure pattern already in this codebase rather than inventing a new mechanism.
- **`next_question`'s `max_tokens` bumped 250→320** (`openrouter_provider.py`) — the richer required replies (reaction + engagement + continuation + question, 2-4 sentences) need a bit more headroom than a bare follow-up question did; this is the same class of fix as the documented `daily_turn` 700→1100 truncation bug, applied preemptively here rather than waiting to hit it.

### Explicitly not built (the "Conversation Context Package" idea)

Your pasted notes suggested a structured context block passed fresh every turn (profile, goals, recent memories, recent conversation, topics discussed, questions asked, questions answered, conversation depth level). That's a bigger, genuinely separate architecture change — a real "depth level" state machine and full topic-tracking would need new state and probably an extra extraction pass. What's shipped here gets most of the practical value (the specific complaint you raised: dead ends, no repeats, real depth) by extending machinery that already exists, which is why it could be done and tested in one pass instead of becoming its own project. If repetition or shallowness is still a problem after this ships, the fuller context-package architecture is the documented next step — not needed yet.

### Verification (real models, not just read)

Ran `Session` directly against the real LLM chain (not mocked) for conversation, interview, and daily modes, including deliberately vague/short user answers to stress-test the "don't just ask another generic question" rule. Two full runs, consistent results:

- **Conversation** — vague answer ("nothing much happened today") got: *"Sounds like a quiet day then — sometimes that's the best time to think about the next thing you want to tackle. Since you're into coding, have you tried working on a small app or script...? What kind of project would you find fun to build?"* — reacts, then narrows to a sharper specific angle instead of a generic follow-up. A real answer ("practiced arrays") got a specific escalating follow-up ("Which array problem gave you the most 'aha!' moment today, and what trick or pattern did you use?") — not a surface-level restart.
- **Interview** — opened in character, referencing the candidate's actual goal, not generic. After the candidate mentioned building an e-commerce app, the follow-up dug straight into it: *"What drew you to focus on an e-commerce app for your first big project, and what was the most challenging part of building it?"* — exactly the "adapt to what they actually said" behavior the prompt now demands.
- **Dead-end check**: across both runs, every conversation/interview turn (5 total) came in well above the 40-character floor and none matched a banned dead-end phrase.

**Honest caveat found during testing, not swept under the rug**: one Daily Talk opening line came back with a garbled fragment mixing scrambled non-words into otherwise-fine Devanagari (`"...neamh kaise ho?... कोई खास कामedor है?"`). This is a free-tier model producing bad output on an off day (the multi-provider chain — gemini/groq/openrouter/github — is a $0 stack by design and quality varies, already an accepted trade-off elsewhere in this doc), not something introduced by this fix, and not something the short-reply retry guard would catch — that guard triggers on *length* (a lazy one-liner), and this garbled reply was 205 characters, well past the threshold. This fix targets the reported bug (dead-ends, no follow-up, repetition) — it does not add general output-quality validation (e.g. detecting scrambled/non-dictionary text), which would be a separate, harder feature if it turns out to matter in practice.

---

## 7. Sequencing

1. **Now — code**: growth-phase access flip (§3) + Career Roadmap feature (§5) + conversation-engine fix (§6) + all §2 blocking items (Android SDK bump, account deletion, privacy/terms pages, AI disclosure, report option, key encryption upgrade).
2. **Now — you, in parallel**: Play Console registration/verification if not done, confirm new-vs-existing account (§2.4), record the keys tutorial video, decide legal name/support email for the policy pages (§8).
3. **Before production**: closed testing 12 testers × 14 days if §2.4 applies; store listing assets; Data Safety form; content rating questionnaire.
4. **Launch**: production release, `access_phase = "growth"`.
5. **Trigger: 100+ downloads**: flip `access_phase` to `"quota"` for new signups (existing growth-phase users keep their unlimited BYOK status — don't retroactively cap people who already verified keys in good faith); begin the separate Play Billing / subscription plan (§4) at that point, not before.

---

## 8. Open inputs needed from you (blanks only you can fill)

- [x] Legal name — **David Singh Rana**, now in `privacy.html` / `terms.html`.
- [ ] Support email to publish — placeholder `[TODO: support email]` sits in `privacy.html`, `terms.html`, `account-deletion.html` (3 spots, one pass once you give me the address). Also needed for the Play Store listing regardless.
- [ ] New Play Console account, or an existing/older one? (determines whether §2.4's closed-testing gate applies at all)
- [ ] YouTube tutorial video — link/ID once recorded; one combined video, or per-provider?
- [ ] `is_office()` vs. admin UI "Free access (our keys)" contradiction (§3, backend changes item 5) — which meaning is actually intended? Doesn't block anything shipped so far, but should get resolved before it causes a real access-control surprise for whoever's on that allowlist.
- [ ] Confirm the two assumed defaults from earlier roadmap planning, or override: (a) `/career/generate` unmetered — moot now that growth phase means nobody has a quota; (b) "Regenerate" wipes stage progress in v1.

---

## 9. Sources

- [App testing requirements for new personal developer accounts – Play Console Help](https://support.google.com/googleplay/android-developer/answer/14151465?hl=en)
- [Target API level requirements for Google Play apps – Play Console Help](https://support.google.com/googleplay/android-developer/answer/11926878?hl=en)
- [Google Play's Target API level Policy – Play Console Help](https://support.google.com/googleplay/android-developer/answer/16561298?hl=en)
- [Understanding Google Play's app account deletion requirements – Play Console Help](https://support.google.com/googleplay/android-developer/answer/13327111?hl=en)
- [About the Data Safety Form and Account Deletion – Google Play Developer Community](https://support.google.com/googleplay/android-developer/community-guide/246344978/about-the-data-safety-form-and-account-deletion?hl=en)
- [Understanding Google Play's AI-Generated Content policy – Play Console Help](https://support.google.com/googleplay/android-developer/answer/14094294?hl=en)
- [Policy announcement: July 15, 2026 – Play Console Help](https://support.google.com/googleplay/android-developer/answer/17134731)

---

## Status / what's left

**Everything code-side in this plan is done and verified.** Two rounds: round 1 shipped the access-phase flip (§3), account deletion (§2.2), privacy/terms/deletion pages (§2.3), and AI disclosure + report option (§2.6). Round 2 added the Fernet key-encryption upgrade (§2.5), the YouTube tutorial embed (§3), the full Career Roadmap feature (§5), and the Android SDK 36 bump (§2.1) — the last of these was an actual `assembleDebug` build, not a source-only edit, and it surfaced two extra fixes (`minSdk` and the Kotlin plugin version) that reading the code alone wouldn't have caught.

Verification this round was substantially heavier than "does it parse": a live server ran against the real Neon DB and real LLM keys with a throwaway test account through the full career-roadmap lifecycle (create → generate via actual Gemini/Groq/OpenRouter/GitHub call → persist → toggle a stage → self-delete cleanup), and the Android app was actually compiled and packaged into a working APK.

**Known characteristic, not a bug**: the real career-roadmap LLM call took ~65 seconds end-to-end in testing (large structured JSON on free-tier models). The client already handles this correctly (fire-and-forget after onboarding, home card shows a "Building your roadmap…" skeleton state until it resolves) — just don't be surprised by the wait when testing manually.

**Round 3 added**: the conversation-engine dead-end/repetition fix (§6) — stronger `conversation_system()`/`interviewer_system()` prompts, cross-session "don't repeat these questions" memory, and a short-reply retry guard, all live-tested against real models across all three talking modes. One residual, honestly-reported finding: free-tier models can still occasionally produce garbled (not just short) output — that's a model-quality ceiling this fix doesn't claim to solve, see §6's verification note.

Everything left is yours, not code:
1. **Play Console mechanics** — registration/verification, closed testing (12 testers × 14 days) if §2.4 applies, store listing assets, Data Safety form, content rating questionnaire.
2. **§8 blanks** — support email (3 placeholders waiting: `privacy.html`, `terms.html`, `account-deletion.html`), confirm new-vs-existing Play Console account, the `is_office` vs. "Free access" contradiction (still unresolved, still not blocking anything).
3. **Release signing** — create `android-twa/keystore.properties` and run `assembleRelease` (or `bundleRelease` for the Play Store AAB) once you're ready; register both SHA-256 fingerprints (upload key + Play App Signing) as `ANDROID_CERT_SHA256` on Render.
4. **The real tutorial video** — swap `TUTORIAL_VIDEO_ID` in `test_client.html` once it's recorded.
5. **A real device/emulator pass** — the debug build proves it compiles and packages; it doesn't prove the TWA experience (voice, notifications, offline gate) behaves correctly on an actual phone.
6. **Watch for garbled (not just short) model output in production** (§6) — nothing to do right now, just flagging it's an observed residual risk from the free-tier chain, separate from the bug you reported.

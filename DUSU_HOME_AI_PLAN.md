# DUSU — Home Page 2.0, "AI Companion First" — Plan + status

> **Status 2026-10-10: audited, designed, then built in the same pass** (owner: "make full solid plan and implement, push code, SSH, test end to end").
> Ships behind `settings.home_ai` = off / **owner (default)** / on (dashboard → Access → "Home AI companion"). **Switch OFF = today's Home, byte for byte.**
> Status, verification and what is *not* verified: §10. Also covers the Android "browser X + URL bar" bug: §9.

## 0. How the request was read
| Phrase | Decision |
|---|---|
| "full Hinglish, not *suprabhat* / good morning … speak Hindi like smart speaking" | DuSu talks like a smart, modern young Indian friend: **Hinglish ~55% Hindi (Devanagari) / ~45% English (Latin)**, short punchy lines. **Never** the stiff greetings (सुप्रभात, शुभ संध्या, नमस्कार) or Sanskritised words (प्राथमिकता, अभिवादन) — it says "Good morning", "Good evening", "priority". Romanised Hindi is never used (the voice mispronounces it). DuSu is a woman and never guesses the learner's gender |
| Home 2.0 spec (pasted) | One primary action on Home — **talk to DuSu**. Home shows a live, time-aware greeting; **Start Speaking** opens the *main AI conversation* (DuSu speaks first); a separate **Know About DuSu** page; Daily Talk and every other mode stay exactly where they are |
| "push code, connect SSH, test end to end" | Push to GitHub, deploy over SSH, then test the real thing (scratch DB on the deployed image with the real model, a browser run against the deployed page, live smoke) |
| "fix the app bug — no browser cross/URL, should be an app" | §9: measured cause + what I could fix + the one input only the owner can supply |

## 1. Audit — verified facts (2026-10-10)
| Area | Fact | Consequence |
|---|---|---|
| Home today | `#startSpeak` → `startDaily("speak")` = **Daily Talk**; headline/sub/welcome bubble are English; stat chips, Speaker Rank, League, Today card sit *above* the button | Start Speaking is currently the same thing as the Daily tab — the spec wants them separate |
| Dormant code | "Companion Moment" (`openMoment`, `POST /greeting`, `GREETING_SYSTEM` = Hinglish ~55/45 from memory) exists but is unused | Reuse the *idea* (Hinglish, one memory callback), not the single-shot UI |
| Session screen | `#session` + `startSession` + `speak`/`startListening`/`orb`/`thinkShow` = a complete voice loop with auto-listen, loaders, errors, language switch | The main conversation **reuses it** as `mode:"home"` instead of cloning a second voice stack |
| Context | `life.py` gives DuSu the learner's exact numbers (level, streak, rank, roadmap, career-goal stages, missions) and has the `EXTRA_LINES` hook | "Mera goal kitna complete hua?" is answerable from real data today |
| Tasks / goals / planner | **Not built** (`DUSU_GOALS_PLAN.md` is plan-only) | "Aaj ka plan?" must say honestly there are **no saved tasks**; Know About shows Goals & Planning as **Coming soon**; nothing promises reminders |
| Language layer | `LG`/`I18N`/`lgt()` (Hindi ⇄ English), flags `bilingual`, `life_context` | Home strings go through the same layer; the Home AI is Hinglish by default and follows the switch if the learner picks English |
| Flags | `practice_room`, `life_context`, `bilingual` = off/owner/on, default owner/off | `home_ai` is the fourth; `/me.home_ai` |
| Android | TWA `com.dusu.app`; live assetlinks = the **upload key only** | §9 |

## 2. Design

### 2.1 Home (flag on)
Order: avatar → **label** "DuSu · your AI companion · Morning" → **greeting bubble** (instant, no network) → 4 **suggestion chips** → **Start Speaking** → **Know About DuSu** → a **type box** ("या यहाँ type करके बताओ…") → the existing cards (Speaker Rank, stats, journey…) pushed *below* by CSS `order`, nothing deleted. The English headline/sub are hidden. Bottom navigation untouched (Daily stays a tab).

**Greeting service** (client, version-controlled copy, no LLM call): 4 time segments (morning 5–11, afternoon 12–16, evening 17–20, night 21–4) × 3 variants, a **new-learner** variant, and an English set; never the same variant twice in a row (remembered per device); first name when known; **no private data** (no tasks, goals, numbers) — the spoken opening is safe when others can hear.

### 2.2 The conversation (`mode:"home"` on the existing WebSocket)
- **DuSu speaks first**: tapping Start Speaking speaks the greeting that is on screen at once (no model wait), opens the socket with that greeting as turn 1, then listens. A chip skips the greeting and goes straight to answering that request.
- One model call per turn returns `{reply, intent, suggest[]}`. **Intents** are a fixed list (`daily_plan`, `goal_progress`, `english_practice`, `confidence_practice`, `interview_prep`, `translate_help`, `presentation_prep`, `feature_discovery`, `general_conversation`); **`suggest` holds feature ids, never URLs**. The server validates both, keeps only features that exist *and are enabled for that user*, caps at 3, and falls back to a deterministic keyword intent detector if the model's JSON is bad. The client maps ids → existing routes; **navigation only happens when the learner taps** — the AI never navigates or changes anything.
- **Honesty rules in the prompt**: only what's in CONTEXT; saved tasks = none (planner not available) → say so, offer to talk through priorities out loud, *don't* claim to save or remind; numbers only if listed; memory only if listed; features only from the live catalog. No romance, तुम/आप never तू, no gendered guesses.
- **Context** = memory (`facts_summary`) + the learner's real numbers (`life.build`) + time of day + new/returning. A **privacy switch** ("use my saved info on Home") removes memory and numbers from the prompt.
- **Persistence**: memory, summary, next-hook and the recent-turns tail are saved (so Daily/Talk can continue the thread); **no XP, streak, league, vocabulary or badges** — a guide chat must not be farmable.
- **Controls**: speak, type (always visible), tap the orb to **interrupt**, **restart**, **End**, back to Home. **Text mode** = typing, mic denied or no recogniser (Firefox): a visible notice, no voice in or out (replies are shown, not spoken), the 🎤 button switches back; the greeting is not spoken when the chat was started by a chip or typed text. After every turn the page scrolls to the newest line (the input row is sticky above the bottom nav).

### 2.3 Know About DuSu (`/about`)
Cards come from **one server registry** (`home_content.FEATURES`, Hindi + English copy, `live`/`soon`, `needs` flag): Main AI Companion, Daily Talk, Face-to-Face English, Interview Mode, Learn (Hindi ⇄ English), Your English Journey, Practice Room (only if enabled for that user), plus "and more" (Career Path, Weekly League, Achievements). **Goals & Daily Planning = Coming soon, no link.** The same registry feeds the AI's "what exists" list and validates its chips — so the page, the chips and the AI can't disagree. Each card carries a "best for" line. Sections: What DuSu can do · And more · Coming soon · How DuSu works (3 steps) · Your privacy (the switch) · Start Speaking.

### 2.4 Acceptance criteria → how verified
| Spec checklist | Verified by |
|---|---|
| AI is the focus of Home; greeting follows local time; Start Speaking starts the conversation; text fallback; Know About opens | Chromium run (fake clock for 4 time segments + new learner, fake socket/voice) |
| AI speaks first; natural Hinglish; recognises the five intents; never invents tasks or memory; chips open the right feature | Real model on a scratch DB (style heuristics: Devanagari share, banned words, length, one question; honesty checks with and without data) |
| Daily Talk stays in the menu; existing modes work; cards accurate; unavailable features not shown as working; Home reachable without losing anything | Old-vs-new diff with the flag OFF; chip → Daily Talk opens the unchanged flow; the registry test |
| Mic denial / voice failure fallbacks; visible states; only authorised data; no sensitive greeting; phone + desktop | Browser run with a recogniser that fails; privacy-switch test; screenshots |

## 3. Interfaces
`/me` + `home_ai` (bool) + `home_prefs`; `GET /home/features?lang=` (the registry for this user); `POST /home/prefs {personal}`; WS `start {mode:"home", opening, seed?, lang, hour}` → `home_ready {lang}`; `user_text` → `home_turn {text, lang, intent, actions[{id,label,route}]}` (or `home_error` / `quota` / `limit`); admin switch `home_ai`; owner tools for the Android fingerprint (§9).

## 4. Risks
Model JSON glitches (~1 in 9 on the lite model) → one retry + keyword fallback + a spoken "say that again"; free-tier quota → counts as a session like the other modes; Hindi quality is checked with heuristics here, **voice quality on a real phone is not**; the new layout is CSS-ordered so the old one returns the moment the switch is off.

## 9. The Android app showing the browser X + address bar

**Measured cause (2026-10-10).** A Trusted Web Activity drops Chrome's toolbar only if Digital Asset Links verifies for the signing certificate of the *installed* app.
- The shipped `DuSu-app.apk` (release v1.1) is signed with the upload key `EF:02:68:…:CD:62:0D`; `/.well-known/assetlinks.json` lists exactly that key on **both** hostnames, and Google's own checker (`digitalassetlinks.googleapis.com/v1/assetlinks:check`) answers `linked: true` for it on `dusu.ranabrothers.online` and `dusu.ruralrootcloud.com`. So the **sideloaded release APK is already correct**.
- A copy installed **from Google Play** is re-signed by Google (Play App Signing). Its certificate is a different key — Play Console → *Setup → App signing → "App signing key certificate" SHA-256* — and that key is **not** in `assetlinks.json`. Chrome cannot verify the link, so it falls back to a Custom Tab: the X and the URL bar. (A debug-signed build shows the same bar for the same reason; never share one.)
- Links that leave the DuSu origin (the Google sign-in popup, "Get a free key ↗") open in a Custom Tab by design — that is not this bug.

**What I changed:** the fix needs one value only the owner can read, so I removed every other obstacle.
- `assetlinks.json` now serves the server's fingerprint(s) from `ANDROID_CERT_SHA256` **plus up to 3 the owner adds at runtime** (Settings table `android_cert_extra`, compact hex, same colon format on the wire).
- Owner dashboard → **Android app link**: shows every listed fingerprint, an *Add* box (any spelling), *Remove* for dashboard-added ones, and **Check with Google** (per host × fingerprint, ✅/❌) — no SSH, no redeploy. Endpoints `GET/POST /admin/applink`, `POST /admin/applink/check` (owner only).

**Owner steps (≈ 2 minutes):** Play Console → DuSu → *Setup → App signing* → copy **App signing key certificate → SHA-256** → DuSu dashboard (More → Dashboard) → *Android app link* → paste → **Add** → **Check with Google** until both hosts show ✅ → on the phone, uninstall the Play build, reinstall it from the closed-test link (Chrome caches the verdict). I cannot do this step for you, and I did not add a made-up or debug key.

**Not verified:** a Play-installed build losing its bar (needs the fingerprint above and a phone).

## 10. Status — built, tested and deployed 2026-10-10
Filled in at the end of the build (see CLAUDE.md §12 for the code map, gotchas and the verification record).

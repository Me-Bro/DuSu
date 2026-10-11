# DUSU — Language scope: the Hindi / English mode belongs to the NEW features only — Plan + status

> **Status 2026-10-11: planned, then built in the same pass** (owner: "keep old features same no matter Hindi or English mode … keep them as it is, don't change them … the new features keep separate, only they have the Hindi/English mode … the DB is shared so it gets to know all … make solid plan and implement").
> **Rule after this change:** Daily Talk, Face-to-Face, Interview, Learn, Journey (and the screens around them) run **exactly as they did before any language mode existed** — whatever the switch, the saved preference, the dashboard flag or the client sends. Only the **new** features (Home AI companion, Know About DuSu, later My Day) have the Hindi ⇄ English choice. One database, one memory, shared by all.
> Verification (the proof that old = old): §4. **Status: §6 - built and tested.**

## 0. How the request was read
| Phrase | Decision |
|---|---|
| "keep old feature same no matter hindi or english mode" | The mode never reaches an old feature: not the language of the chat, not the prompts, not the screen text, not the scoring, not the voice/recogniser locale |
| "daily talk same flow, Hindi talk and feature" | Daily Talk = the original: the learner speaks Hindi/Hinglish, DuSu answers in Hindi, the English line + tip card, resume, +20 XP. No English Daily, no switch |
| "face to face / the interview / the convert Hindi to English / the journey" | Face-to-Face stays English; Interview stays English (English report); Learn stays **Hindi → English** only (no direction switch); Journey and the bottom nav stay English |
| "keep them as it is, don't change them" | Target = **byte-identical to the pre-language baseline `6db1979`** (server prompts + model inputs + side effects; client text + voice + wire). This also **reverts my voice polish** on Daily Talk / Face-to-Face (it changed old-feature output) |
| "new features separate, only they have Hindi/English mode" | A registry of the modes that obey the choice: `lang.SWITCHABLE = ("home",)`; the switch is drawn only on Home, in the Home chat and on Know About; My Day joins later by adding its mode |
| "db shared so DB can get to know all" | Unchanged and extended: one Postgres, one `memory.facts`; the Home companion reads everything the old features wrote — now **also what the learner told Daily Talk today/yesterday** (mood, plans, events) — and the language preference is stored in the DB (`memory.facts.lang_pref`) |

## 1. Audit — where the mode reached into old features (measured 2026-10-11)
| Layer | What the language mode did to an old feature | Where |
|---|---|---|
| Server | picked the session language for `conversation` / `interview` / `daily` / `learning` from the client (`lang`) | `main.py` WS `start` (`_lang`, `bilingual_on`) |
| Server | Hindi Face-to-Face + Hindi Interview prompts, English Daily Talk prompt, English→Hindi translator, Hindi scorer + report | `prompts.py`, `engine.py` |
| Server | mid-chat `lang` frame; Hindi sessions scored with vocabulary/grammar unscored, no vocab growth, no English-only badges | `main.py` (`lang` branch, `_persist_session`) |
| Client | one pill in the header of Talk / Daily / Learn, one on the Interview set-up, a direction switch in Learn | `LG.mount()` |
| Client | rewrote **static text of old screens** (bottom nav, Practice hub, Interview set-up, report, session result, Daily, Learn) in Hindi | `LG_STATIC`, `applyStatic` |
| Client | rewrote every old-screen string through `lgt()` and set `<html lang>` (which also switches CSS line-height rules) | `tr()`, `applyUI()` |
| Client | picked the recogniser locale + voice per mode, and let server frame tags (`lang`, `dir`) steer Daily / Learn / Talk | `LG.lang()`, `speak()`, `greetDaily`, `handleDailyTurn`, `handleTranslation` |
| Dashboard | the switch was described as "Talk, Interview and Daily Talk in Hindi or English" | `bilSel` row |

## 2. Decisions
| # | Decision |
|---|---|
| D1 | **One registry** decides which modes obey the choice: `lang.SWITCHABLE = ("home",)`. Everything else is pinned to `lang.LEGACY` (what it always was). Adding a new feature = one word here + drawing its own switch |
| D2 | **Server:** for a mode not in `SWITCHABLE`, `bilingual_on` is False and `_lang = LEGACY[mode]` whatever the flag / pref / client `lang`; the `lang` frame is ignored for it. So an old session is built exactly as before the language mode existed (the path already proven byte-identical) |
| D3 | **Client:** `LG.lang(mode)` returns `LEGACY[mode]` for old modes; `tr()`/`lgt()` is language-aware **only inside the Home companion chat** (and Home/Know About use `HM`'s own copy) — every other string is the original English; frame tags `lang`/`dir` are ignored for old modes; `<html lang>` is never changed |
| D4 | **Remove the old-screen language UI:** pills in Talk / Daily / Learn / Interview set-up, the Learn direction switch, `LG_STATIC` + `applyStatic`, `applyLearn`, `setDir`. The pill exists only on Home, in the Home chat header and on Know About |
| D5 | **Parked, not deleted:** the Hindi/English prompts, engine branches and `I18N.hi` strings for old modes stay in the code, unreachable, documented as parked (the owner may want them one day: add the mode to `SWITCHABLE` and re-draw its switch) |
| D6 | **Revert the voice polish** (`Session(polish=)` on Daily Talk / Face-to-Face). `soften()` stays — for the Home companion only |
| D7 | `bilingual` flag (off / owner / on) now means "the Hindi/English switch is available **on the new features**"; with it off the new features are Hinglish only. Dashboard copy says so. `/lang` keeps accepting `learn` (ignored) for old clients |
| D8 | **Shared DB, extended:** the Home prompt gets "what they told Daily Talk" (`facts.daily_context`: mood / plans / weather / events / notes, today + yesterday) next to memory + the learner's numbers — grounded in the DB, never presented as a saved task list. Old features keep reading the same memory (a Home chat tail already reaches them as "your Home chat") |
| D9 | The Practice Room keeps its own language choice (Hindi / Hinglish / English in its set-up) — it is a new feature, unaffected |

## 3. Design
**Server.** `lang.py`: `SWITCHABLE`, `session_lang(mode, requested, switch_on)` (→ `norm(requested)` only for a switchable mode with the switch on, else `LEGACY[mode]`). `main.py` WS `start`: `bilingual_on = mode in SWITCHABLE and await bilingual_enabled(email)`; `_lang = session_lang(...)`; `Session(..., bilingual=bilingual_on)`; the `lang` frame already returns early when `bilingual_on` is False. `engine.py`/`main.py`: delete the `polish` parameter and its three call sites. Home context: `_daily_context_str(facts)` appended (personal only) under its own heading; `_HOME_RULES` gets one bullet on how to use it.

**Client.** `LG` becomes the *new-feature* language layer: `SWITCHABLE = {home:true}`; `lang(mode)`; `tr()` (Home chat → user's language, anything else → original English); `pills()` shows each switch only where it belongs (`data-lg-sw=""` Home page + Know About, `"chat"` only while `currentMode === "home"`); `live()` only for the Home chat; no direction, no static rewriting, no `<html lang>`. Call sites that read `LG.on()` / frame tags in old flows (`thinkSteps`, the `translate_error` voice, `speak`, `greetDaily`, `handleDailyTurn`, `handleTranslation`) read the pinned values instead. `HM` draws the About pill and keeps the pills in step on `onSessionShown`.

## 4. Verification — the proof that "old = old"
| # | Check | Pass when |
|---|---|---|
| P1 | **Server A/B** (host, scratch DB, model stubbed): the same WebSocket scenarios for Face-to-Face, Interview, Daily Talk, Learn run on the pre-language baseline code (`6db1979`) and on the new code with the switch **ON**, saved pref `en/en` and `hi/hi`, and a client that sends `lang:"en"`, `lang:"hi"` and a `lang` frame | every model call (system prompt, transcript/payload, kwargs), every frame to the client (minus the new `lang`/`dir` tags) and every DB side effect (conversation rows, XP, streak, vocabulary, badges, score rows, report entry) is **identical** to the baseline |
| P2 | **Client A/B** (Chromium, fake socket / recogniser / voice): the pre-language client (`test_client.before_bilingual.html`) vs the new client with `bilingual:true` and `lang`=`hi`/`en`, `learn_dir`=`en` — a dump of every old screen's text, the bottom nav, and the full Talk / Interview / Daily / Learn flows (orb labels, spoken text + voice, recogniser locale, wire frames) | identical JSON; `<html lang>` stays `en`; no pill anywhere except Home / Home chat / Know About |
| P3 | New features still bilingual: Home greeting / chips / chat / Know About in Hindi and English, the pill, persistence of the choice, Know About pill | the existing 117-check suite (updated for the new pills) |
| P4 | Real stack (browser → WebSocket → new code → scratch DB → real model), owner with the switch ON and saved `en`: Daily Talk answers in Hindi with the English card, Face-to-Face in English, Interview in English with an English report, Learn Hindi → English; Home chat still obeys English | all behave as before; Home chat English |
| P5 | Live smoke on both hostnames + the deployed HTML through P2 | pass |

## 5. Rollout & rollback
No flag to flip: old features are pinned for everyone the moment this deploys; only the owner could ever have seen the old-mode switch (default `owner`). Rollback = redeploy `10130ec` (the previous commit). The saved `lang_pref` stays valid (Home uses it).

## 6. Status — built and tested 2026-10-11
**Built.** Server: `lang.py` (`SWITCHABLE`, `session_lang`), `main.py` (WS `start` pins every old mode; Home also gets Daily Talk's today/yesterday notes via `_home_daily_block`; docstrings), `engine.py` (the voice polish removed), `prompts.py` (one rule bullet for the Daily Talk block). Client: `LG` rewritten (registry, pinned `lang()`, `tr()` language-aware only in the Home chat, `pills()` per context, no static re-writing, no `<html lang>`, no Learn direction), `LG_STATIC` deleted, call sites pinned (`thinkSteps`, `translate_error` voice, `speak`, `greetDaily`, `handleDailyTurn`, `handleTranslation`), a language change on Know About re-fetches the page, the switch is drawn only when `bilingual` **and** Home AI are on, dashboard copy rewritten, dead CSS removed; `sw.js` → `dusu-v22`.

**Verified - old = old is proven by DIFF (each harness was also run on the previous commit and FAILS there, so it can fail).**
| # | Result |
|---|---|
| P1 server A/B | 180 scenarios (6 mode values × 6 `lang` values × 5 mid-session `lang`-frame sequences) through the real `/ws/interview` handler, stub model: pre-language tree `6db1979` vs new tree, switch OFF and ON → **1,350 frames + 630 model calls identical**; all 1,140 language tags on old-mode frames are the legacy ones. Previous commit: 14/180 identical, 854 non-legacy tags |
| P2 client A/B | 89 observations (whole text of every old screen, nav, `<html lang>`, voice, recogniser locale, wire frames of Talk / Interview / Daily / Learn) **identical** to the pre-language client in 7 variants: switch off · on+`hi` · on+`en` with a device-cached choice · hostile server tags (`lang:"en"` on Daily, `dir:"en2hi"` on Learn) · runtime flips through the real pill · with and without Home AI. Previous commit's client: 29 observations leaked |
| P3 new features | Home 117/117; boundary 55/55 (switch only on Home / Home chat / Know About; flipping it re-writes Home and changes **not one** old screen; switch on + Home AI off draws nothing); Know About re-fetch on its own switch; 138 pure-logic checks (`session_lang` for every old mode × request × switch, `Session` built the way the handler builds it == the default Session, no `polish` parameter, the Daily Talk block, `/me.home_tiles`) |
| P4 real stack | 112 scratch-DB checks with the real model (switch ON for everyone: Talk / Interview open in English although Hindi was asked; Daily stays Hindi; Learn stays Hindi → English; a `lang` frame is ignored; Home obeys the choice and **knows what Daily Talk learned** - "कल HR interview है न…" - without claiming to have saved it) + **41 real end-to-end checks** (real Chromium → real HTTP + WebSocket → new code → scratch DB → real model): with English saved and the switch on, Daily Talk opens in Hindi with the original card, Face-to-Face opens in English, Learn translates Hindi → English |
| P5 live | **Deployed 2026-10-11 (commit `1edf981`, container healthy, server files byte-identical to the tested tree).** Live smoke on both hostnames: 26/26 (new client + icons + scope client present, `sw.js` `dusu-v22`, anonymous callers refused, assetlinks unchanged, deep links). The DEPLOYED html (fetched from the live site; Cloudflare's email obfuscation undone) through the same suites: client A/B 89/89 × 7 variants identical, boundary 55/55, icon grid 28/28, Home 117/117 |
Two test bugs of mine were found and fixed on the way (a negative marker "HR interview" that is also in the always-present feature catalogue; an assertion that the original Daily mic label is Hindi - it is "Answer in Hindi", copied now from the old client). Style warnings from the live model (a `देख लो` / `जाइए` register slip in 2 of ~14 replies) are informational and unrelated.

**Not verified:** a real phone (Hindi voice quality, Hinglish recogniser accuracy, Devanagari rendering). **Owner decisions left:** (1) the voice polish was removed - say if the owner wants "सुप्रभात" gone from Daily Talk as a separate opt-in; (2) "Home AI → Everyone" and "Hindi / English switch → Everyone" are two separate dashboard switches; (3) the Play Console App-signing SHA-256 for the Android browser bar (`DUSU_HOME_AI_PLAN.md` §9) is still the owner's to paste.

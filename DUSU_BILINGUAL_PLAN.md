# DUSU — Hindi ⇄ English modes (Daily Talk · Face-to-Face · Interview · Learn) — Plan + status

> **⚠ RE-SCOPED 2026-10-11 — read `DUSU_LANGUAGE_SCOPE_PLAN.md` first.** The owner ruled that the Hindi ⇄ English choice belongs to the **new features only** (Home AI companion, Know About DuSu, later My Day). Daily Talk, Face-to-Face, Interview, Learn and Journey are **pinned to what they were before this plan**, whatever the switch, the saved choice or the client says. The all-modes design below is kept in the code but **parked** (unreachable until a mode is added to `lang.SWITCHABLE` and its switch is drawn again), and the verification in §9 describes that parked design - it is **not** today's behaviour. The voice polish mentioned for Home was removed for the same reason.

> **Status 2026-10-10: designed, then built in the same pass** (owner said "make solid plan and implement").
> Ships behind `settings.bilingual` = off / **owner (default)** / on. **Switch OFF = today's behaviour, byte for byte** (Face-to-Face and Interview English-only, Daily Talk Hindi-in, Learn Hindi→English).
> What is built, what is verified and what is not: §9. What is deliberately left for a second pass: §8.

## 0. How the request was read
> "all in Hindi — both English and Hindi modes, with a switch — Daily Talk, Interview, Face-to-Face English and Hindi→English under the same rules — the new modules too — default Hindi."

| Phrase | Decision |
|---|---|
| "switch Hindi ⇄ English … same rules" | **One global language** (`hi` / `en`) that every voice mode obeys, switchable **before and during** a session, sticky, saved per account |
| "Hindi to English" (Learn) | Learn is a translator, so it gets its **own direction**: *speak Hindi → hear English* (default) or *speak English → hear Hindi*. It is **not** tied to the global language (a learner who practises English in Face-to-Face still wants Hindi→English in Learn) |
| "default should be Hindi" | A user who never chose gets **Hindi** (`DEFAULT_LANG = "hi"`). The choice is sticky, so it is a first-use default, not a lock |
| "these new modules" | **Practice Room**: default talk language Hindi (it already had en / hi / hinglish). **My Day** (planned, not built): the plan now requires Hindi/English UI from day one (`DUSU_GOALS_PLAN.md` §4, D12) |
| "so don't face any issues" | Switching mid-chat never restarts it; replies are tagged with the language they were written in, so a late reply is spoken with the right voice; Hindi sessions don't get scored on English grammar/vocabulary |

**Honest conflict to know about:** "default Hindi" also applies to **Face-to-Face "English" Talk and Interview**, whose whole point is English practice. I did what was asked; one tap flips it and the choice sticks. The mode names/blurbs adapt to the language ("आमने-सामने बातचीत" in Hindi).

## 1. The rules (the contract every mode follows)
1. Language ∈ {`hi`, `en`}. Default `hi`. Saved per account (`memory.facts.lang_pref`) and cached in `localStorage.dusu_lang`.
2. The **same toggle** (`हिंदी | English`) sits in the header of Face-to-Face, Interview, Daily Talk and Learn, on the Interview set-up card, and on Home. It changes the language of: what the learner **speaks** (speech recogniser), what DuSu **says** (text + voice), and the **screen text**.
3. **Switching mid-session**: the socket stays open; the server swaps the prompt; the next reply is in the new language; the mic restarts in the new recogniser language; a one-line confirmation is spoken. Nothing is lost.
4. Every server reply carries the language it was written in (`lang`), so a reply that lands after a switch is still spoken with the right voice.
5. **Scoring/persistence:** a Hindi session is not scored on English vocabulary/grammar (stored `NULL`, `overall` renormalised — the Practice Room machinery); spoken-English vocabulary isn't grown from Hindi; the English-only badges ("Spoke without Hindi", "Asked a question in English") aren't awarded. XP, streak, missions work the same in both languages.
6. **Script:** Hindi is written in **Devanagari with English words kept in Latin** (`interview`, `practice`) — romanised Hindi is mispronounced by the voice. DuSu speaks as a woman (matches the avatar and voice) and **never guesses the learner's gender** (no रहे हो/रही हो — neutral wording or imperatives). तुम/आप only, never तू (existing `HINDI_RESPECT_RULE`).

## 2. Mode matrix

| Mode | Hindi (default) | English |
|---|---|---|
| **Daily Talk** | unchanged: Hindi friend chat, learner's line shown *translated to English* + tip | **new** English friend chat; the card shows *a better way to say it* (their line polished) + an English tip; no translation step |
| **Face-to-Face** | **new** Hindi conversation (mic `hi-IN`, Hindi voice) | unchanged |
| **Interview** | **new** Hindi interview; report in Hindi, rubric **without** English grammar/vocabulary | unchanged |
| **Learn** | direction *Hindi → English* (unchanged) | direction *English → Hindi* (**new**): speak English, hear natural Hindi |

## 3. Server design
| Piece | Where |
|---|---|
| Helpers: `norm`, `DEFAULT_LANG`, `LEGACY` (what "switch off" means per mode), fallback lines in both languages, the switch note | `backend/app/lang.py` |
| Prompts: `conversation_system(lang)`, `interviewer_system(lang)` (Hindi variants), `DAILY_TURN_SYSTEM_EN`, `TRANSLATE_SYSTEM_EN2HI`, `scorer_system(lang)` | `interview/prompts.py` |
| `Session(lang=)`, `set_lang()` (rebuilds the prompt; a transient "learner switched to X" note rides on the next user turn only — never stored), language-aware caps/closers/nudges, `translate` direction, `daily_turn` by language, report tagged with `lang`, memory pass told the session language | `interview/engine.py` |
| Flag `bilingual_mode()/bilingual_enabled()` (off/owner/on, default owner); WS `start` carries `lang`; new frame `{"type":"lang"}` → `lang_ok`; replies carry `lang`; `translation` carries `dir`; persistence rules (§1.5); `/me` returns `bilingual` + `lang` + `learn_dir`; `POST /lang`; admin switch | `main.py` |
| `save_lang_pref` / `get_lang_pref` (schemaless, no migration); interview reports keep their `lang` | `db.py` |
| Practice Room default talk language → `hi` | `db._PRACTICE_PREF_DEFAULTS` |

## 4. Client design
`LG` module + `I18N` table + `t(key)` (one block, early in the script). Static text carries `data-i18n`; **the original English text is remembered on first apply and restored if the switch is off**, so flag-off is exact. `I18N.legacy` holds the few strings whose legacy wording differs from the new English one (e.g. Daily's "🎤 Answer in Hindi"). Per mode: recogniser locale, voice, orb/loader/state labels, report labels (missing metrics are skipped, not shown as 0), session-result rows. Hindi text uses `html[lang=hi]` line-height so matras aren't clipped.

## 5. Rollout
`settings.bilingual` off / **owner** / on, dashboard → Access. Default **owner** so the owner (and the unlimited account) try it first; flip to Everyone when happy. The Play closed-test users see nothing change until then.

## 6. Verification plan
Tier 1 offline (key parity en/hi, prompt routing, fallbacks); tier 2 scratch Postgres on the host with the **real model** (Hindi Face-to-Face, mid-chat switch, Hindi Interview + report, English Daily, English→Hindi Learn, legacy parity when off); tier 3 Chromium look with a stub socket in both languages and a mid-session switch; live checks after deploy. **Not possible here:** a real phone (Hindi voice quality, Devanagari rendering on the owner's handset, recogniser accuracy for Hinglish).

## 7. Decisions taken
| # | Decision |
|---|---|
| B1 | One global language + Learn's own direction (above) |
| B2 | `bilingual` switch, default **owner** (not "everyone") — it changes every conversation |
| B3 | English speech recogniser stays `en-US` (the proven path); Hindi `hi-IN` |
| B4 | Hindi UI text in Devanagari + Latin loanwords (matches the existing assessment copy) |
| B5 | Daily Talk English mode: `english` = polished line (not a translation), so it does **not** count toward "thoughts translated to English" |
| B6 | JSON key names `reply_hindi` / `next_question_hindi` kept for English Daily too (contract stability) — they carry the reply in the session language |

## 8. Second pass (not in this build)
Home hero copy, Journey, Ranks/League, Profile, Keys, Settings, More sheet, Help, Level-check screens other than the (already bilingual) assessment, **Practice Room screens** (its talk language is switchable; its chrome is English), and **My Day** (not built). All use the same `data-i18n` + `t()` mechanism — add keys, no new machinery. Also: Hindi push/reminder copy for My Day; `/letter` and Companion greeting language follow-up.

## 9. Status — BUILT 2026-10-10 (switch default: owner only; nothing changes for other users until it is flipped)

**Built as designed** (CLAUDE.md §11 has the file map): `lang.py`, Hindi/English prompts, `Session(lang)` + `set_lang`, WS `lang` frame + tagged replies, `/me` + `POST /lang`, persistence rules for Hindi sessions, dashboard switch, the client `LG`/`I18N` layer with the switch on Home, Talk, Interview set-up, Daily and Learn (+ Learn's direction control), Hindi report/result/loader/orb text, Practice Room default talk language `hi`.

**Verified**
| What | How | Result |
|---|---|---|
| Switch OFF = today, server | old HEAD vs new code, same scenarios (13 model calls: retry path, turn caps, interview marker, Daily retry, report, memory pass) | byte-identical prompts, model inputs and fallback lines |
| Switch OFF = today, client | old vs new client, 55 observations (static text on 8 screens, orb/loader/state text, TTS language+voice, recogniser locale, wire payloads, report + result rows) | identical |
| Server on a scratch Postgres, real model | 62 checks: `/me`, `/lang`, admin switch, wiring of all four modes, the one-off switch note (once, never stored), persistence rules, legacy parity with the real model, and the language quality below | all pass, 0 warnings |
| Language quality (real model) | Hindi Talk opening + reply (Devanagari, ≤ 70 words, ends with a question, no तू, no gendered forms for the learner), switch to English → the very next reply is English, and back; Hindi interview (4 questions stay Hindi, formal) + report (valid JSON, `lang:"hi"`, only the 4 applicable scores, Hindi feedback, no तू); English Daily (reply English, `english` = the line polished, tip in English); Hindi Daily (Hindi reply + English translation); English→Hindi Learn on 3 sentences; Hindi→English still English | pass |
| Client in Chromium (fake socket / recogniser / voice) | 42 checks: Hindi by default, switching mid-chat sends the frame + saves the choice + speaks a confirmation, a late Hindi reply is still spoken with the Hindi voice, Hindi report shows only the 4 metrics, English Daily shows "a better way to say it" and does not recite it, Learn direction flips recogniser + voice + card label, flag-off restores the original text | all pass; screenshots reviewed on phone and desktop |

**Found and fixed while testing:** (1) `LG` is a top-level `const` (not `window.LG`) — harness issue only; (2) `#shareBtn` had no Hindi label; (3) the model guessed the learner's gender once in an opening line → the rule now lists explicit neutral rewrites and says to mirror only what the learner reveals; (4) the first Hindi prompt let English words dominate (~50%) → now "about three quarters Hindi"; (5) the interviewer now uses आप.

**Not verified (needs the owner's phone):** Hindi TTS voice availability/quality on Android Chrome (the app picks a `hi-IN` voice if the phone has one), recogniser accuracy for Hinglish, Devanagari font rendering on the handset, battery/permissions are unchanged. **Not done (second pass, §8):** the remaining screens and the Practice Room / My Day chrome.

**Decision to revisit:** "default Hindi" makes *Face-to-Face English Talk* and *Interview* open in Hindi for a first-time user. It is one constant (`lang.DEFAULT_LANG`) and the choice is sticky; say if you want those two to default to English instead.

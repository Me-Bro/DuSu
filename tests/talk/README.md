# Talk tests (server side, milestone M5 of the learner-first release)

Talk = ONE door with three support levels: **Hindi -> English** (Daily Talk's engine, UNCHANGED, WS mode `daily`), **English + Hindi subtitles** (`en_sub`) and **English only** (`en`) - the two
new levels are the new WS mode `talk`, driven by a topic card of the day. Package `backend/app/talk/`: `topics.py` (bank loader, validator, "today's topic"), `reply.py` (what one model reply
becomes: cleaning + the fix verified by code), `service.py` + `api.py` (the screen's HTTP side, prefix `/tk`), the engine is `Session.talk_turn` in `backend/app/interview/engine.py`, the
prompt is `talk_system` in `interview/prompts.py`. Switch `settings.talk_v3` = off (default) / owner (+ early access) / on. **The topic bank itself** (`backend/app/talk/bank/a1.py`,
`a2.py`, `b1.py`, 30 topics each) is authored separately; these tests use their own fixtures (`fixtures.py`) and never depend on it, except `unit_topics.py`'s one live check that
whatever IS authored passes the lint.

Nothing here touches the app's own database or a real provider: the server tiers run on a scratch MongoDB on an `--internal` docker network (`tests/lib/scratch_mongo.sh`), the model is a
scripted stub, no key exists anywhere.

| tier | command (repo root) | what it proves |
|---|---|---|
| pure: bank | `python3 tests/talk/unit_topics.py` | the validator (ids, bands, categories, focus = a Grammar Lab unit, 3 starters, 6-8 vocab, **Hindi: Devanagari, no आप / तू, no second-person verb that guesses gender, no gendered first person in a starter**, unique ids / titles / openers), the defensive loader (a missing band module = that band empty; a module that raises = an error entry, never a crash), `today()` (deterministic, in band, no repeat inside a week, categories alternate), `alternatives()`, band / default-support mapping, copies not live rows, the lint script's exit codes |
| pure: reply | `python3 tests/talk/unit_reply.py` | the prompt (contents, **<= 1,500 estimated tokens for the whole call even at its worst**), the walk's own `check`, cleaning of `reply` / `hi`, and **the fix verified by Grammar Coach's machinery**: a real slip is shown; case / punctuation / homophone / numeral / contraction / filler / repeat "fixes" are dropped; a quote not in the message, a rewrite, an empty fix, a free word swap, a fix that would introduce a mistake are dropped; two fixes become one |
| engine | `tests/talk/run.sh --nomongo unit_engine.py` | `Session.talk_turn` with a stub model: the opener makes NO model call; **exactly one call per turn** with the validated-walk arguments (`schema`, `check`, <= 500 tokens); only English reaches the transcript; a failed turn leaves the session as it was; legacy walker retries once, validated walk never; the stub mirrors the real interface (`json_accept` is run on its replies) |
| HTTP | `tests/talk/run.sh selftest.py` | switch off / owner / early access / on (401, 404, 403), `/tk/state` shape and defaults per level, `/tk/topic`, `/tk/prefs` (validated, per learner, kept beside the rest of the memory, deleted with the account), rate limit, an empty bank, dashboard + `/admin/settings`, the Home registry (Talk appears only while the switch is on for the account), `_MODE_BONUS`, missions and badges |
| WebSocket | `tests/talk/run.sh ws_selftest.py` | the REAL handler: a start with the switch off / unknown topic / bad support never builds a Session; the opener is one frame with no model call; one call per turn; `hi` only at `en_sub`; `fix` only when verified, at most one; no Devanagari / JSON in the transcript or the memory pass; failure -> error frame + refund + line taken back; the cap; the quiet reconnect; `end` persists once and pays once; a dropped socket is still saved; Grammar Coach is not involved |
| real walk | `tests/talk/run.sh wire_walk.py` | NO stub of `llm`: the real handler, the real `llm.assess(schema=, check=)` and the real walker with scripted fake providers (`tests/keys/world.py`): one provider request for a good turn; with `chain_v3` on, prose / JSON without `reply` / a Hindi-only `reply` moves to the NEXT provider inside the same turn; nothing usable = the retry pop-up's `error` frame (`kp` transient, never "your keys"), one pass over the models, the free turn refunded, the line not kept; `chain_v3` off = the old walker and Talk's own single retry |
| old = old | `tests/talk/parity.sh` | the same scripted scenarios for every pre-existing mode (conversation, seed, reconnect, interview, daily, daily reconnect, learning, home, practice, unknown mode, an empty end) against `tests/.baselines/lab-done/backend`, the tree with the switch OFF and with it ON: **frames, every model call's full input and the database effects identical**; `/me` and Know About differ only by the additive `talk_v3` flag / the Talk tile; the Home registry, the language registry and every old prompt are byte-identical; `mode:"talk"` with the switch off is a refusal where the old code silently made an interview |
| planted bugs | `python3 tests/talk/mutants.py [pure\|engine\|http\|ws\|wire\|all]` | each deliberate bug, one at a time in a copy of the backend, must be caught by some test (see below) |
| owner-run | `tests/talk/real_model.py` | NOT run by anything here (no keys). Real chain: Hindi quality of the subtitle (raw), latency, how often a fix is proposed / verified / dropped. Needs `TALK_REAL=1` and your own keys in the environment |

`TALK_BACKEND_DIR=<dir>` tests a copy; `TALK_BACKEND_DIR=baked TALK_TEST_IMAGE=dusu-backend:<tag> tests/talk/run.sh ...` tests the code baked into a built image.

## For the authors of the topic bank
`python3 tests/talk/lint_topics.py [a1|a2|b1]` (or `--file path.py`): exits 1 on any error; run it until it is clean. The schema and the Hindi rules are at the top of
`backend/app/talk/topics.py`. A row the server cannot validate is skipped at load (and logged once), never half-loaded.

---

## Wire contract (for the client)

### What exists and how it is gated
`/me.talk_v3` (bool) says whether this account has the new levels. Off -> draw nothing new; the Hindi -> English level is Daily Talk and is not behind the switch. With `home_ai` on and the
switch on, `/me.home_tiles` carries `{id:"talk", icon:"🗣️", route:"/talk", t:{hi,en}}` and Know About lists it. Client route is **`/talk`**, API prefix is **`/tk`** (an API prefix equal to
a client route would be shadowed by the SPA fallback).

### HTTP (all need `Authorization: Bearer <session token>` or `?token=`; 401 not signed in; **404 while the switch is off for the account**; 403 blocked; 429 `{"detail":{"error":"slow_down"}}` after 60 requests a minute)
* `GET /tk/state` ->
  `{enabled:true, date:"YYYY-MM-DD" (IST), level:"A1"|"" (the learner's stored CEFR), band:"A1"|"A2"|"B1", support:"hi"|"en_sub"|"en" (the level to preselect), support_chosen:bool (they chose it themselves),
  support_default:"hi"|"en_sub"|"en" (computed from the level: A0/A1 -> hi, A2 -> en_sub, B1/B2 -> en), topic:<topic>|null, alternatives:[<brief> x3], levels:[<level> x3], empty:bool, reviewed:bool}`
  * `<topic>` = `{id, band, cat, title:{en,hi}, opener:{en,hi}, starters:[{en,hi} x3], vocab:[{en,hi} x6..8], focus:"present_simple"|...}` (`focus` is a Grammar Lab unit id: link to `/grammar-lab/<focus>`).
  * `<brief>` = `{id, title:{en,hi}, band, cat, focus}` - "Choose another topic" shows these (3); fetch the full card with `/tk/topic/{id}` when one is tapped.
  * `<level>` = `{id:"hi"|"en_sub"|"en", ws_mode:"daily"|"talk", label:{en,hi}, hint:{en,hi}}` - **`ws_mode` is the WebSocket mode to start for that level** (`hi` -> `daily`, UNCHANGED frames; the other two -> `talk`).
  * `empty:true` with `topic:null` = no topic is authored yet (an empty bank is a normal answer, never a 500): show "topics are coming soon".
  * Today's topic is the same all IST day for a learner and does not repeat for at least a week; the three alternatives are stable for the day too.
* `GET /tk/topic/{id}` -> `<topic>`; 404 for an unknown id (any band is allowed: the learner may pick another band's topic).
* `POST /tk/prefs {support:"hi"|"en_sub"|"en"}` -> `{support}`; 422 `{"detail":{"error":"support"}}` for anything else. Saved in `memory.facts.talk_prefs` (per learner, deleted with the account).
* Hindi in all of the above is unreviewed (`reviewed:false`): Devanagari for Hindi words + Latin for everyday English words, तुम, no gendered second person.

### WebSocket `/ws/interview` - the `talk` mode
**Client -> server**
* `{type:"start", mode:"talk", token, keys, topic_id:"<id>", support:"en_sub"|"en", hour, tzmin?, name?}`. `support:"hi"` is **refused** (that level is `mode:"daily"`). Everything else in `start` is as for Face-to-Face.
  A start the server cannot serve is answered with ONE `error` frame and the socket is closed - nothing was created: `{type:"error", msg:"Talk is not available for this account yet." | "Pick a topic to talk about." | "Unknown Talk level."}`
  (plus the usual `auth_error`, `keys_required`, blocked-account `error`).
* `{type:"user_text", text}` (<= 600 characters are used), `{type:"end"}`, `{type:"ping"}` (-> `pong`), `{type:"close"}`.
* **Reconnect** (screen lock): the same `start` frame again with `reconnect:true`, `resume:[{role:"user"|"assistant", content}, ...]` (<= 60 lines), `elapsed` (seconds, ignored for talk). Exactly the boolean `true` counts;
  an empty / junk `resume` is an ordinary start (the opener comes again).

**Server -> client**
* Opening (no model call, the topic card's own opener): exactly one frame
  `{type:"ai_text", text:<opener.en>, lang:"en", hi?:<opener.hi>, topic:{id, title:{en,hi}}}` - `hi` ONLY at `support:"en_sub"`. No `status`, no `home_ready`.
* Each `user_text`: `{type:"status", msg:"thinking"}` then **one** `{type:"ai_text", text, lang:"en", hi?, fix?}`:
  * `text` = DuSu's English reply (1-2 short sentences, ends with a question); speak it with the English voice. `hi` = its Hindi subtitle, only at `en_sub`, and **absent whenever the server could not vouch for it**
    (the Hindi rules failed) - show nothing in that case, never invent one.
  * `fix` (additive, absent on most turns, **at most one**) = `{q, f, r, c, full, w?}` and belongs to the learner's line THIS reply answers (the one just sent): `q` = their words exactly as they wrote them,
    `f` = the replacement, `r` = the reason in English, `w` = the reason in Hindi (only at `en_sub`, only if it passed the Hindi rules), `c` = `"sure"` (a rule check agrees - word it firmly: "better: ...") or
    `"likely"` (word it softly: "you could say ..."), `full` = the whole learner message with the fix applied, built by code (use it for the "Hear it" button). Show the card UNDER THEIR OWN bubble after DuSu answers,
    never interrupting; an older client that ignores `fix` / `hi` / `topic` keeps working (the keys are additive on `ai_text`).
* At the turn cap (`conversation_max_turns`, 40): the cap reply arrives as a normal `ai_text`, then `{type:"limit", msg}`; a further `user_text` gets `limit` only (no model call, the free turn is not spent).
* Failure of a turn: `{type:"error", msg:"Could not get a reply - please try again.", kp?}` (the AI could not answer: **the learner's line was NOT kept by the server and the free turn was given back** - re-send the same text
  on the same socket, exactly like Face-to-Face / Home: `KY.problem(kp)` / the retry pop-up) or `{type:"quota", msg, kp}` (the learner's OWN keys are rejected / at their limit). Existing frames, `quota_update` / `quota_exceeded`, unchanged.
* After a reconnect: `{type:"session_resumed", mode:"talk", lang:"en"}` and NOTHING else - no opener, no model call; the replayed lines are context only and the turn count restarts at 0 (the first socket already saved and
  rewarded its turns when it closed). Resend an unanswered last learner line after it, exactly as for Face-to-Face.
* `end`: `{type:"speaker_progress", data}` (and maybe `mission_progress`) then `{type:"ended"}` - the client closes on `ended`, so progress always comes first. A chat with no learner turn writes nothing. A dropped socket is still saved.
* Rewards: XP is `_MODE_BONUS["talk"] = 15` (equal to Face-to-Face: Talk IS Face-to-Face with a topic and a correction per turn; listed explicitly so an unlisted mode is not silently booked as "conversation" and a later change to
  Face-to-Face does not silently move Talk). A Talk chat counts toward the weekly "Face to Face Talk sessions" mission, the Fearless Speaker / Conversation Builder badges, and earns the first-chat badge. **Grammar Coach is NOT
  involved in v1**: send no `gref`, expect no `grammar_ref`.

### What the client must do
1. **Language registry.** `talk` is **NOT** in `LG` `SWITCHABLE`; add it to `LG.LEGACY` as `"en"` (mirror of `backend/app/lang.py`: `LEGACY["talk"] = "en"`, `SWITCHABLE = ("home",)` unchanged). The session language is English; the Hindi is
   a *subtitle the learner chose with the Talk screen's support level*, drawn from the frame's `hi` key, whatever `LG` says. The global Hindi / English switch must not change a word of the Talk chat. Screen chrome follows the
   same rule as the other new screens (a toggle of its own or the learner's saved choice), not `LG.tr()` inside the chat.
2. **Reconnect machinery (`VP`).** Add `"talk"` to `VP.SESS` (the modes `owns()` covers) so a lock pauses and a return revives it. `sessFrame` is the `start` frame; `sessRevive()` re-sends it with `reconnect:true` and `resume:sessReplay()`
   (the server's `_RESUMABLE` already includes `talk`). **The replay is read back from the page: `sessLog()` takes `.msg .bubble` `textContent` of every `#feed .msg:not(.thinking)`** - so the Hindi subtitle, the fix card, the vocabulary
   chips and anything else Talk draws must live OUTSIDE `.bubble` (as siblings inside `.msg`, or in their own element): a subtitle inside a bubble would be sent back to the model as if DuSu had said it in Hindi.
3. Handle `session_resumed` for `mode:"talk"` like the other session modes (restore the screen, re-send an unanswered last line). Keep `topic_id` and `support` in the stored `start` frame so a revive opens the same topic.
4. `support:"hi"` (Hindi -> English) is `startDaily(...)` exactly as today - do not send it to the `talk` mode.
5. The mic stays `en-US` (the learner speaks English); the English voice reads `text`; the subtitle is read by nobody. A `fix` card's "Hear" speaks `full`.
6. The Talk entry points (Home tile, nav, More row) draw only while `/me.talk_v3`; the route `/talk` is a rollout-flagged route (wait for the first `/me` on a cold deep link, like `/grammar-lab`).

---

## Decisions taken (and gaps filled)
* **Unknown / unusable start = a plain `error` frame + close, never a Session** (the same refusal as Home / Practice). `Session.__init__` silently turns an unknown mode into an interview, so the `talk` start is validated in `main.py` BEFORE any
  Session exists. This is the one deliberate difference from the old code (`mode:"talk"` used to become an interview) - `parity_compare.py` asserts both sides.
* **`talk` is not switchable** (`lang.py`): the support level is Talk's own language choice; making it switchable would let the client's `lang` / `lang` frames and the global switch reach it, and score it as a Hindi chat.
* **The fix is shown only if `grammar/verify.py` verifies it** (located as whole tokens, bounded edit, not a recogniser artifact, no opaque token) AND its corrected message, built by code, passes `build_corrected`'s post-conditions
  (token bounds, no new digit, **no new mistake the rule checks can see**) AND, unless a rule check agrees (`c:"sure"`), it is a *grammar* edit (an inflection / irregular form / helping verb / article / preposition / pronoun) - a
  swap of one content word for another is a style opinion and is dropped. Level floor A2 for the "unlabelled mark" gate: Grammar Coach never shows an unlabelled mark to an A1 learner because it has no explanation; every Talk fix carries
  its own reason. `rule` ids are not exposed (the model is not asked for them).
* **`hi` / `w` follow the Hindi rules and are dropped, never repaired**, when they break them (आप / तू, a verb that guesses gender); the English reply and the fix still go out.
* **No second walk and no check on `hi` inside the validated walk**: `schema={"reply":"str+"}` plus `check` (reply must be English) only. A model that merely omits / spoils the subtitle must not be held back for everyone's Home / Daily chat (the
  held-back state is per kind of call, `json`, shared with them).
* **Prompt budget**: system + topic <= ~850 estimated tokens, chat window 8 lines x 200 characters, learner message <= 500 characters -> whole call <= 1,500 (pessimistic estimator, asserted for the worst legal topic). Talk loads only the memory
  (a <= 240 character "about the learner" line) and the profile level - not the long memory block, summaries, relationship tone or the life numbers.
* **Talk joins the shared systems explicitly** (each one a silent default otherwise): `db._MODE_BONUS["talk"]` (15), the weekly `conversation_sessions` mission + Fearless Speaker / Conversation Builder counts, `courage_first_convo`,
  `life._MODE_LABELS`, `main._facts_summary`'s "where you left off" label, `_RESUMABLE`, `home_content.FEATURES`.
* **`today()` is stateless** (a per-learner fixed order of the band, categories taking turns, indexed by the IST day number): deterministic, no history to store, no repeat for as many days as the band has topics. An unauthored band falls back to the
  nearest authored one so a learner is never offered nothing.
* **Hindi tokenisation**: the danda (U+0964 / U+0965) lies inside the Devanagari block, so a word right before "।" is only a whole token if the tokenizer excludes it (planted bug P10).

## Planted bugs
`python3 tests/talk/mutants.py all`: 61 deliberate bugs, one at a time (11 bank, 12 reply, 10 engine + 1 prompt-budget, 3 real-walk, 13 WebSocket, 11 HTTP; the list is in `mutants.py`); every one must be caught. One *equivalent* mutant is deliberately not listed: switching off only
"the quote is located in the message" changes nothing because the corrected-message post-condition drops the same fix (layered defence); R9 switches both off and is caught. The same layering is why S9 (Grammar Coach wired into Talk) edits three places - the mode list, the persist hook and `gating.session_gate` - and W2 drops both the schema and the check.

## Not verified (only a real phone / real providers / a native reader can)
Hindi quality of the subtitle and of the `w` reasons with a real model (`real_model.py`), real latency with the Devanagari field, STT artifacts on a real phone (the artifact filter is tested on hand-made cases), the voice loop of the new screen on
Android, the Hindi wording of the three level labels (`service.LEVELS`) and of the `talk` registry entry, a native read of the topic bank.

---

# Client (the `TK` module of `backend/test_client.html`, built 2026-11-17 - NOT committed, NOT deployed)

One screen, `#tk` (route `/talk`, API `/tk`), and the Talk chat on the existing `#session` screen. Gated by `/me.talk_v3` (`FLAG_ROUTES` has `/talk`, so a cold deep link waits for the first `/me`, falls back
Home after 12 s, and goes Home if the switch is off). Hindi -> English is **Daily Talk**: the Start button calls `navTo("/daily-talk")`, so its own route, socket and frames are used and the module never builds a
daily frame. English + Hindi subtitles and English only are the `talk` WebSocket mode.

| Where | What |
|---|---|
| `TK` module (after `GL`) | the topic card (title en + hi, three starter chips = a hint panel with a Hear button, never a send; 6-8 useful words with Hindi; the grammar-focus chip - a link to `/grammar-lab/<focus>` only while `/me.grammar_lab`, a plain label otherwise), the level switch (a radio group preselecting `support`, remembered with `POST /tk/prefs`), "choose another topic" (the 3 alternatives, `GET /tk/topic/{id}`, a way back to today's), an empty bank = "topics are coming soon" (never an error), Escape closes the hint / the list, the screen's own Hindi / English toggle (`dusu_tk_lang`, Hindi default); `startChat()`, `onAi()`, the correction card, `tryAgain()`, the end-of-chat list; DOM-builder only (no `innerHTML`), CSS `tk-*` / `#tk*` only |
| the chat | `start {type, mode:"talk", token, keys, topic_id, support, hour, tzmin, day, name}` kept in `sessFrame` (a revive re-sends it with `reconnect:true` and the replay); the opener = ONE bubble; the Hindi subtitle is a **sibling of `.bubble`** inside `.msg` (`.tk-m` makes that message a grid), the correction card is a child of `#feed` placed right after the learner's `.msg.user` (so it is in no `.msg` and in no bubble - `sessLog()` reads only `.bubble`, so neither can ever be sent back to the model); the card is drawn when DuSu's speech has ended (`aiSpeaking` false, or at once if nothing is spoken) and scrolled into view above the bottom nav; `sure` = "Better", `likely` = "You could say"; Hear it = `speak(full)`, Try again = the mic now; a subtitle toggle (`#tkSubBtn`, `dusu_tk_sub`, on by default, hides the Hindi reason on cards too) |
| one-line hooks in shared code | `LG.LEGACY.talk = "en"` (NOT in `SWITCHABLE`) + `LG.applySession` leaves a Talk header to `TK`; `VP` `SESS` += `talk`; `onMessage`: `ai_text` -> `TK.onAi` for Talk, `ended` keeps the session-result screen for Talk, `speaker_progress` -> `TK.afterSessionResult`; `leave()` returns a Talk chat to `/talk`; `show()` (`TK.onSessionShown`, `TK.leave`, `TK.syncEntries`), `openMore`, `refreshMe`, `logout` (`TK.reset`); `addMsg` now returns its element; `pathForScreen`, `NAV_TAB.tk`, `PATH_TAB["/talk"]`, More row `#mrowTK`, Practice-hub entry `#tkEntry`, Home tile icon, dashboard select `#tkSel` (+ a health line), `sw.js` `dusu-v45` |
| privacy | one bullet in `privacy.html`, a clause in `terms.html` and `account-deletion.html` (the Talk server stores what Face-to-Face stores plus `talk_prefs.support`) |

**Deviations from / notes on the wire contract.** None on the wire. Extras the contract does not list: `day` in the start frame (every chat sends it; the server ignores it) and the reconnect adds `seed:""`, `opening:""`, `plan:false`
(the shared `sessRevive` does; the server ignores them for talk). The fix card shows `q` -> `f` and the reason; `full` is only spoken (Hear it). A stray `hi` at English only is ignored client-side as well. The Practice-hub
entry says "Talk" like the existing "Talk" mode card of the same hub (Face to Face): the names are the owner's, and Know About / the Home tile use the registry's "Talk".

## Client tests (`tests/talk/browser/`; every tier on scratch infrastructure: a scratch MongoDB on an `--internal` docker network, a scripted Talk model (`talk_stub.py`), scripted fake providers, no key anywhere)

| tier | command (repo root) | what it proves |
|---|---|---|
| real browser | `tests/talk/browser/run_real.sh real.spec.cjs` (`ONLY=B3,C1` / `SECTIONS=A,B`) | real Chromium -> a WebSocket proxy -> the REAL app + real topic bank + scripted model: **A** the card, starters (a hint, nothing sent, Escape), the level switch remembered (also after a reload), another topic (the chat opens THAT topic), the focus link / label, an empty bank, the screen's language, Hindi -> English really opens Daily Talk with exactly today's frame keys and nothing for the talk mode, default level per CEFR, entry points (Practice hub, More, Home tile), the switch off (cold, stale cache, per account), a cold deep link, a second routing pass; **B** the start frame, one opener bubble, the subtitle as a sibling, English only spoken, `en-US` mic, the card under the learner's line **only after speech ends**, Hear it / Try again, `sure` / `likely` wording, a dropped fix, a lock + dead socket + unlock re-opens the SAME topic and level with a replay of exactly the bubbles (no Hindi, no card text) and no second opener, the subtitle toggle (remembered), the top-3 list on the result screen, one reward, Back; **C** a failed turn -> the retry pop-up, the SAME words again, no banner; a key-limit frame and the turn cap; **D** the global switch changes nothing; **E** markup from the model or the topic bank is text; **F** layout at 360 / 390 / 1280 in both languages (screenshots in `~/.cache/dusu-tk-shots/`), tab order + focus rings |
| static | `ORIG_HTML_HOST=<abs path in the repo> tests/talk/browser/run.sh static.spec.cjs` | no `innerHTML`-family call and no `.bubble` in the module; TXT / CH key parity and use; the Hindi house rules (look-arounds, not `\b`); every wiring point; CSS rooted in `.tk-*` / `#tk`, nothing under 12 px; the inline scripts compile; the weight added |
| old = old | `ORIG_HTML_HOST=<abs path in the repo> tests/talk/browser/run.sh oldnew.spec.cjs` | the page BEFORE Talk against the page after, switch OFF and ON: text, element order, static DOM and pixels of 15 old screens at 360 / 390 / 1280. The baseline is a copy of `backend/test_client.html` taken before the first Talk edit (it holds the then-uncommitted Grammar Lab and provider work, so it isolates Talk's change only); it lives in `tests/talk/.tmp/` while the work is done and is deleted afterwards - once Talk is committed use `git show <the commit before Talk>:backend/test_client.html`. OFF: the only differences are the dashboard's new Talk row (text) and the hidden `tk*` markup; ON: also the Practice hub's Talk entry and the More sheet's Talk row, nothing else |
| planted bugs | `MUT_JOBS=3 python3 tests/talk/browser/mutants.py [M3 ...]` | 35 deliberate client bugs, one at a time (a subtitle inside the bubble, a card inside a bubble / at the end of the feed / drawn during speech, Hindi -> English sent to the talk mode, a `support:"hi"` frame, `innerHTML` for model text / a topic title, the global switch reaching the chat, a retry that sends nothing, a revive that loses `topic_id`, a flag-off entry point, a replay that reads the whole message, Try again without the mic, ...), each must fail a named spec |

`TK_BACKEND=<dir>` tests a copy; `TK_BACKEND=baked TK_TEST_IMAGE=dusu-backend:<tag>` the code inside an image. `tests/store/browser_all.sh talk talk_static` runs the first two.

**Not verified (only a real phone / a native reader can):** the Hindi wording of everything `TK` draws (`TXT.hi`, `CH.hi`: **UNREVIEWED**) and of the server's level labels; real `SpeechRecognition` / TTS behaviour of the new screen on Android (the specs use a fake
recogniser and a speech stub), the correction card's timing against a real voice, a real lock screen (the proxy kills the socket and the page is hidden by an override), the card on a real handset with the on-screen keyboard.

**Verified (2026-11-17, scratch infrastructure only):** real-browser spec **405 / 405** (31 scenarios; the first full run was 387 with 0 failures, the later ones added a cold-deep-link "never Home first" check, the entry-point control, the free-session-limit scenario, arrow keys, and the `hint` pressed-state bug the first run caught - `aria-pressed` compared a string with a number); static **341 / 341** (the page grows by about 12 KB behind gzip, 348,863 -> 360,843 bytes); old = old **48 / 48** (Talk OFF: text, element order and all 45 screenshots identical except the hidden `tk*` markup and the dashboard's Talk row; Talk ON: only the Practice hub and the More sheet differ); **35 planted client bugs, all caught** (the first pass left one alive - M10, "the Talk entry is drawn while the switch is off": the spec looked for the entry on a screen that was not open; it now opens the Practice hub and checks a control entry - and M35 was added later; A11 / A12 / D1 were also made stricter while the batch ran - the route guard and the flag route were otherwise only visible through a transient state - and the mutants that depend on them were caught by the stricter checks). Re-run against the tree: page audit `verify.cjs` **307 / 307** (Talk switch off), Grammar Lab real **266 / 266**, "the AI did not answer" **308 / 308**, lock / unlock **166 / 166**, session chats lock **343 / 343** (see the note), keys `sw.spec` **62 / 62** (pin moved to `dusu-v45`), keys `static.spec` **92 / 92**. The Lab's own `oldnew.spec.cjs` (against the page before the Lab) is **26 / 28**: its two failures are Talk's additive markup and the dashboard's Talk row, which that older spec's strip list and allowance do not know (a throw-away copy with `#tkEntry, #mrowTK, #tk, #tkSubBtn` and `Talk|tkSel` added passes both; the original spec was NOT edited - update its strip list when Talk ships).

*Flakes under load, said plainly:* one `lock2.spec.cjs` run of the regression pass reported 67 passed / 35 failed - every failure from the 7th scenario on read "waitForResponse /me timed out", and the server log said `dv-scratch-mongo-...: Temporary failure in name resolution`: the scratch MongoDB container had vanished mid-run (the host was at a load average of 10-15 and other jobs were running). Re-run alone it passed **343 / 343**. A second run of the Lab's old = old showed a 41-pixel difference on the 1280 px Home page that the first run (45 / 45 identical) did not have: the documented self-comparison noise of animated screens.

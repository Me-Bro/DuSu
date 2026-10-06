# DuSu — Practice Room · Product & Engineering Plan

> Drafted 2026-10-06 from the owner's product spec (Presentation / Viva / Discussion / Speech / Seminar / Custom practice → score → listen back → fix → retry → see improvement). **Language modes (Hindi · Hinglish · English) added the same day — §13.** **Status: Phase 1 + the bridge are built and shipped dark — §14.**
> This turns the spec into a build plan grounded in the **current** codebase. **✔** = measured on 2026-10-06. *(verify)* / *(assumption)* = not yet proven — each has a spike in §8.
> Related: `DUSU_SPEAKER_PROGRESSION_PLAN.md` (XP/rank/league — Practice Room plugs into it), `PLAYSTORE_CLOSED_TEST_PLAN.md` (§12 here).

---

## 0. TL;DR

1. **The idea is right and fits DuSu's strongest user** (college students and job-seekers with a real event coming). "Your presentation is tomorrow? Practice it today" is a better hook than "learn English" — and it gives closed-test testers a concrete reason to return daily.
2. **Two engineering decisions make it feasible** (both deviate from the spec's implied design):
   - **Record → transcribe → analyse, not live speech recognition.** The spec's UX (don't interrupt, analyse at the end) fits it. It avoids Web Speech's known long-session instability on Android and any microphone conflict, and gives word timestamps — which "Mistake Replay" and real pause metrics need.
   - **Hybrid scoring: measured metrics + an evidence-based LLM rubric.** ✔ An LLM separates strong from weak well (≈89 vs ≈52) but **re-scoring the same speech varies by up to 12–15 points**; a naïve "+9 improvement" would often be noise (§4.3).
3. **Three gates must pass before it can ship** (not code problems):
   - **Privacy:** our published policy says *"DuSu does not record, receive or store your voice."* Recording a rehearsal makes that false until the policy + Play Data-safety form are updated (§9).
   - **Audience:** Play lists DuSu as **18+, not for children**. The spec says "school" — position for **college/university students and professionals** (§9).
   - **Transcription key:** the server's Groq key is dead (401 ✔). BYOK users with their own Groq key work today; server-key users need a fresh key (§5.2).
4. **Ship in phases, dark by default.** Phase 0 = 2-day spikes on real phones. Phase 1 = Presentation MVP (~8–10 working days) behind a `practice_room` flag (`off → testers → on`). Viva / Discussion / Custom are Phase 2. Don't put it in front of closed-test testers until the spikes pass (§8, §12).
5. **Hindi, Hinglish and English are a Setup choice, not an afterthought (§13).** ✔ The same talk scores the same in either language (strong talk: Hindi 91.5 vs English 91.8 on the shared skills), so Hindi practice earns full credit; Grammar, Vocabulary and Clarity are English-only categories and are simply not scored for Hindi. DuSu invites English **once per attempt, on the report, as a dismissible card built from the student's own words — never spoken, never repeated** (today's Daily Talk repeats a spoken reminder every 3rd turn — §13.1). Three code traps found while planning this are fixed in the plan (§13.7).

---

## 1. The product — what we keep, change, defer

The spec is strong. These are the engineering-driven adjustments; everything not listed is kept as written.

| Spec idea | Decision | Why |
|---|---|---|
| Don't interrupt during practice; analyse after | **Keep — it's the core UX** | Matches record→analyse; also a real presentation isn't interrupted |
| "Pronunciation 76/100" | **Rename "Clarity" + show a "words to practise" list; no phoneme-level claim** | We have no pronunciation model. Real signal available: Whisper segment confidence + LLM-flagged hard words. Calling it "pronunciation" would be false precision |
| "Confidence 73/100" | **Rename "Steadiness"** (pace consistency, pauses, restarts, hedging) | We measure delivery signals, not emotion. Spec itself says "don't pretend to measure emotions" |
| Filler counts ("umm", "aaa") | **Show only if detected** | Whisper tends to drop fillers; speech-to-text usually does too. Show "you know / basically / actually / like" counts (real words) and hide "um/uh" unless the transcript contains them — never display a fake 0 |
| Weights 20/15/15/15/10/10/5 | **Re-balanced to sum to 100** (§4.2) | The spec's weights sum to 90 |
| "Marks" → "Performance Score" | **Keep** (spec decision) | Right call |
| Listen to yourself, transcript, Mistake Replay | **Keep; recording stays on the phone** | Needs word timestamps (§5) |
| Attempt 1 vs 2 comparison | **Pull into Phase 1** | It *is* the retention loop; cheap once scores exist. Show a delta only above the noise floor (§4.3) |
| Viva / Discussion / Custom | **Phase 2**, built on the existing WebSocket "interview" pattern | Different interaction (turn-based), reuses the examiner/persona engine |
| Gamification, weekly report, streak | **Reuse Speaker Progression** (XP, streak, League, Missions, Achievements) — do not build a second system | Already implemented; Practice Room just feeds it (§6) |
| "College / school" | **College / university / work** | Play audience is 18+ (§9) |
| "Real event date" | **Add** an optional "When is it?" field | Creates an event → Home banner "Your presentation is tomorrow — one more run?" (event system exists ✔) |

---

## 2. User journey & where it lives

**Placement (decided by what exists):** the Practice hub currently shows 3 cards (Learn, Talk, Interview) and ends with a placeholder **"More modes coming soon 🔜"** ✔ — Practice Room replaces that placeholder and becomes the top section. Home gets one card: *"Presentation tomorrow? Practice it today."* The 6-tab bottom nav is already full — **no new tab**. New route `/practice-room`.

```
Practice hub → Practice Room (6 cards) → Setup → Mic check + 3-2-1 → LIVE → Analysing → Report
                                                                              ↑                 │
                                                           Practice again ◄───┴── History / Compare
```

| Screen | Content |
|---|---|
| **PR-1 Hub** | Presentation · Viva · Discussion · Speech · Seminar · Custom (Phase 1 shows Presentation; others "Soon"). "My practice" strip (last attempts) |
| **PR-2 Setup** | Topic (text), duration chips 2 / 5 / 10 / custom, difficulty (Beginner / Intermediate / Advanced → adjusts the rubric's expectations, not the scoring scale), goal chips, optional date, **language chips — "I'll speak in" Hindi / Hinglish / English and "Feedback in" Hinglish / English** (§13.3) |
| **PR-3 Mic check** | Level meter, "say hello", permission handling, tips, 3-2-1 |
| **PR-4 Live** | Timer `03:42 / 05:00`, recording dot, live level meter, **Pause**, **Finish**. Nothing else on screen. Screen kept awake |
| **PR-5 Analysing** | The new thinking loader with honest steps: *Transcribing → Checking structure → Writing feedback* |
| **PR-6 Report** | Score ring + Performance Score; 8 category bars each with a one-line *why*; 3 strengths; 3 fixes; up to 3 grammar fixes ("You said / Better"); "words to practise" with 🔊; transcript (tap a line → audio jumps there); audio player; **Practice again** |
| **PR-7 History / Compare** | Attempts per topic, deltas, trend; delete recording / delete attempt |

Desktop (≥1200 px) follows `DUSU_DESKTOP_UI_PLAN.md`; every new screen gets the same two-column treatment as Session/Report.

---

## 3. What we already have (reuse, don't rebuild)

| Existing | Reuse for |
|---|---|
| Speaker Progression: `award_speaker_progress()` (XP formula, caps 300/session & 600/day, streak rule, `SessionScore`, `WeeklyStat`), `update_weekly_missions()`, `check_achievement_badges()` | Practice attempts earn XP/streak/League/missions like any session (§6) |
| Interview report UI (`.score-ring`, `.metrics` bars, strengths/fixes cards) and `renderSessionResult` | Report layout, bars, cards |
| `llm.assess()` (JSON via `_extract_json`), per-request BYOK chain `set_active_keys`, `resolve_keys` | Analysis call, key handling, 402 flow |
| `settings` table flags (`level_test`, `access_phase`, `owner_byok`) + `/admin/settings` | `practice_room` feature flag |
| `memory.facts.events` + Home `#eventBanner` | "Your presentation is tomorrow" |
| `feedback` table + Help screen | Report thumbs / "was this accurate?" |
| The "DuSu is thinking" loader (shipped 2026-10-04) | PR-5 |
| Account-deletion path (`delete_user`, `admin_wipe_users`) | **Must be extended** — a past audit found new tables were missed here; see B8 |
| Onboarding language choice (`journey.lang`, set in `save_assessment`), the `HI()` / `ENG_SLOW()` voices, `hi-IN` recognition in Daily Talk | Default feedback language; key-phrase playback; live Hindi viva/discussion in Phase 2 (§13) |

**Does not exist yet:** any audio recording, `MediaRecorder`, `getUserMedia`, Wake Lock, or IndexedDB in the client ✔ (grep = 0 hits). This is net-new capability, which is why Phase 0 exists.

---

## 4. Scoring design — the heart of the feature

### 4.1 Principle
Every number needs evidence and a next step. **Measure what can be measured; ask the LLM only for judgements it can ground in quotes.**

### 4.2 Rubric (sums to 100)

| Category | Pts | How it is produced | Shown as |
|---|---:|---|---|
| **Fluency** | 20 | **Measured** from word timestamps: pace (wpm band 110–150 ideal for a presentation), pause ratio, count of pauses >2.5 s, restarts (50 %+30 %) + LLM flow judgement (20 %) | % + "long pause at 02:14" |
| **Grammar** | 15 | Errors/100 words from the LLM's **exact-quote** `grammar_fixes` + LLM judgement | % + top 3 fixes |
| **Vocabulary** | 5 | LLM vs the speaker's level | % |
| **Clarity** *(spec: Pronunciation)* | 10 | Whisper segment confidence (`avg_logprob`) + LLM-flagged hard words | % + "words to practise" |
| **Content** | 20 | LLM: topic coverage, explanation, examples (against the stated topic) | % + "missing: …" |
| **Structure** | 10 | LLM **booleans/counts**: intro?, main points (n), examples (n), conclusion? (a bare "thank you" is not a conclusion) | % + checklist |
| **Steadiness** *(spec: Confidence)* | 10 | Measured pace variance + restarts + hedging words + unfinished sentences, plus LLM | % + one-line tip |
| **Time** | 10 | **Measured**: |actual − target| / target ≤10 % → 100, ≤25 % → 75, ≤50 % → 45, else 20 | % + "over by 3:20" |

*The weights above are the **English** column; Hindi and Hinglish talks use a different set (§13.6).*

`Performance Score = Σ pts × category%`. Band labels: 90+ Excellent · 75–89 Good · 60–74 Developing · <60 Needs practice. Pause time is excluded from speaking time; Pause button time is tracked separately and shown, not scored.

### 4.3 Noise — measured ✔ (this changes the design)
Prototype of the draft prompt on the server's Gemini key: 2 transcripts × 3 runs each.

| Transcript | Runs (overall) | Spread | Sub-score range |
|---|---|---:|---|
| Strong presentation, temp 0.2 | 91, 86, 91 | 5 | up to 7 |
| Weak presentation, temp 0.2 | 51, 58, 46 | **12** | up to 15 |
| Weak presentation, temp 0.7 (what the server uses today) | 58, 50, 43 | **15** | up to 20 |

So the LLM **ranks correctly (gap ≈ 37 points) but is noisy**. Consequences, all part of the build:
- Add a `temperature` parameter to the chain (`_complete` is hard-coded to 0.7 for every call ✔) and use **≤0.2** for scoring.
- **Median of 2–3 parallel runs** (latency is ~3.5 s each, run in parallel).
- Keep ~40 of the 100 points on **measured** categories (Fluency, Time, Clarity, Steadiness-measured) — they don't wobble.
- **Show a delta only if |Δ| ≥ 5** ("+9 — real improvement"); otherwise "about the same". Re-calibrate the 5 on the golden set (S3).
- Calibration set: 15 golden transcripts × 5 runs; target overall σ ≤ 2.5. *(expected, not yet measured)*
- Prompt needs tightening — the prototype counted "So that is my topic. Thank you." as a conclusion.

### 4.4 Guardrails
Minimum 40 words and ≥ 45 s → otherwise "Too short to score — try again" (no XP). Plausibility: wpm ≤ 230, transcript length consistent with timestamps → else `genuine_effort=false` (0.3× XP, excluded from trends — existing rule). All user-supplied text (topic, custom scenario) is passed to the model as **quoted data**, never as instructions; every Practice prompt includes the shared persona boundary block (the anti-romantic/sexual boundary added 2026-09-22).

---

## 5. Architecture

### 5.1 Capture (client)
`MediaRecorder` (`audio/webm;codecs=opus`, ~24 kbps ≈ 0.18 MB/min → a 10-min talk ≈ 1.8 MB), 10 s chunks mirrored to IndexedDB so a crash/interruption doesn't lose the take. Screen Wake Lock while live. Auto-pause when the tab is hidden or a call interrupts (do **not** run the existing `stopAllVoice` path, which would discard the take). Hard cap 15 min. A red "Recording" indicator is always visible; recording never continues in the background. Level meter via `AnalyserNode`.
*(verify on real phones: S1)* permission prompt inside the TWA, behaviour on Redmi/Realme/Samsung, battery/thermal for 10 min.

### 5.2 Transcription — provider order
1. **Groq `whisper-large-v3-turbo`, called directly from the phone with the student's own Groq key.** ✔ Groq's endpoint answers CORS preflight from our origin (`access-control-allow-origin: *`), so **audio never reaches DuSu's servers**. Request `verbose_json` with word + segment timestamps; `language` taken from the Setup choice (`en` / `hi`; Hinglish → `hi`, to be confirmed — §13.5); a short disfluency-preserving prompt *(verify)*. Free tier (secondary sources, verify): ~20 req/min, ~2,000 req/day, ~7,200 audio-sec/hour — a 10-min talk uses 600 s.
2. **Server proxy** `POST /practice/transcribe` for users who ride server keys (tester list / quota phase): audio held in memory only, never stored. **Blocked today:** server Groq key 401 ✔ — needs a fresh key.
3. **Fallback:** Gemini audio (the student's Gemini key), then Web Speech transcript (no replay audio, rough timestamps).
Most BYOK users already hold a Groq key (it's the recommended first key on the setup screen).
*(verify: S2)* Whisper accuracy on Indian-accented English and Hinglish code-mixing; effect of the disfluency prompt; end-to-end latency for 5 min of audio.

### 5.3 Analysis (server)
`POST /practice/analyze` — same shape as `/lesson/evaluate` ✔ (token → `resolve_keys` → 402 → `set_active_keys`). Body: `{kind, topic, level, target_sec, actual_sec, pause_sec, transcript, words:[{w,s,e}], segments:[{s,e,conf}], attempt_of?}`. Server computes the measured metrics, runs the LLM (temp ≤0.2, median of 2–3, `max_tokens` ≥1500 — Daily Talk taught us small limits truncate JSON), merges, applies the formula, persists, returns the report. Per-user daily cap (e.g. 30) + global kill-switch.

### 5.4 Data
New table **`practice_attempts`** (a new table, so `create_all` creates it — no ALTER needed):
`id, user_id, kind, topic, level, target_sec, actual_sec, words, wpm, scores JSONB, report JSONB, attempt_no, parent_id, genuine_effort, created_at`.
**Recordings and full transcripts stay on the device** (IndexedDB `dusu-practice`, keep last 10, user can delete). The server keeps **scores + the report + ≤3 quoted sentences**, not the full text — privacy by default. Trade-off: switching phones loses audio/transcript (history of scores survives). *(decision D4)*

### 5.5 Feature flag
`settings.practice_room = off | testers | on` (same pattern as `level_test`), exposed in `/me`, switchable in the owner dashboard. Code ships dark; nothing changes for anyone until the owner flips it.

---

## 6. Plugging into what exists

| Event | Existing function | Change |
|---|---|---|
| Attempt finished | `award_speaker_progress(uid, mode, minutes, turns, scores, genuine_effort)` | Add modes to `_MODE_BONUS`: `presentation 25, viva 25, speech 20, seminar 20, discussion 15, custom 15`. Map the 8 categories onto the 5 Performance components (confidence←steadiness, continuity←fluency, vocabulary, grammar_trend←grammar, depth←content) so League/Before-vs-Now stay coherent. `turns = max(1, words//40)` so a 3-min talk qualifies for the streak |
| Weekly missions | `update_weekly_missions(uid, mode, minutes, overall)` | Add presentation/viva to eligible modes |
| Achievements | `check_achievement_badges` | New: First Presentation, 10 Presentations, Score ≥ 80, Score ≥ 90, First Viva |
| Companion memory | `add_conversation`, `merge_facts` | Summary "Practised a 5-min presentation on <topic>, score 78"; event `{type:"presentation", date, note}` |
| Home | `#eventBanner` | Generalise the CTA beyond "Practice interview" → "Practice now" for presentation/viva/seminar |
| Account deletion | `delete_user`, `admin_wipe_users` | **Include `practice_attempts`** (B8) |
| XP farming | caps 300/session, 600/day | Unchanged. Residual risk: with direct-to-provider transcription the server can't verify a transcript — accepted, capped by the existing limits |

---

## 7. Phases

### Phase 0 — spikes (≈2 days, needs the owner's phones)
| ID | Question | Pass when |
|---|---|---|
| S1 | Record 10 min inside the **TWA** on 3 budget phones (Redmi/Realme/Samsung): permission, wake lock, interruption, battery | no crash/loss; recording plays back |
| S2 | Whisper (Groq, user key) on 20 real Indian-English / Hinglish samples | usable transcript on ≥85 %; word timestamps present; latency for 5 min < 25 s |
| S3 | Scoring calibration: 15 golden transcripts × 5 runs | overall σ ≤ 2.5; strong vs weak gap ≥ 25 |
| S2b / S3b / S6 | Hindi & Hinglish transcription · per-language calibration and parity · English-invitation policy | see §13.10 |
| S4 | Web Speech + recording at the same time (*optional* — only needed if we want live captions) | informational |
| S5 | Privacy + Play Data-safety review of the final data flow | wording agreed (§9) |

### Phase 1 — Presentation MVP (≈8–10 working days)
**Backend:** B1 flag + `/me` + admin switch · B2 `temperature` plumbing (default stays 0.7 for all existing calls) · B3 `PRACTICE_ANALYSIS_SYSTEM` prompt · B4 metrics + scoring module · B5 `practice_attempts` + db functions · B6 endpoints (`analyze`, `history`, `attempt`, delete; `transcribe` proxy in 1b) · B7 Speaker Progression wiring (§6) · **B8 deletion paths** · B9 rate limit / cost guard / no transcript content in logs.
**Frontend:** F1 hub section · F2 setup · F3 mic check · F4 capture engine · F5 transcription client (+ offline queue: keep the take, retry later) · F6 analysing loader · F7 report · F8 history + attempt comparison · F9 IndexedDB store · F10 desktop layout, reduced-motion, accessibility · F11 routes + Home card + service-worker bump.
**Policy:** P1 privacy page + terms · P2 Play Data-safety · P3 copy review for 18+.
**Maps to the spec's own 16-item MVP list** (Appendix B), plus attempt comparison and history, which the spec put in Phase 2 but the loop needs.

### Phase 2 (≈8 days)
Viva (`viva` examiner mode: turn-by-turn Q&A, knowledge/English/clarity/response-time, "questions to revise") · Discussion (DuSu as a participant; GD report) · Custom scenarios ("act as my professor") · Mistake Replay (tap a mistake → audio jumps) · progress dashboard.

### Phase 3
Weekly report, goals, achievements polish, topic suggestions, presentation templates, adaptive difficulty, share card.

---

## 8. Risks

| Risk | Evidence | Mitigation |
|---|---|---|
| Recording unreliable on budget Android / in the TWA | not yet tested; no recording code exists | S1 before any build; degrade to transcript-only with a clear message |
| Whisper weak on accents / Hinglish | unknown; a third-party model card reports ~9–12 % *character* error for Hindi on clean read speech | S2 / S2b; always set `language` explicitly; show the transcript so users can see what it heard; fallback provider; language-specific risks in §13.11 |
| LLM scoring noise undermines "improvement" | ✔ spread 12–15 | §4.3 (temp, median, measured share, delta threshold) |
| Web Speech instability on Android for long speech | community reports (cited) | designed out — we don't depend on it |
| Server keys unusable | ✔ Groq 401, OpenRouter 404, GitHub dead; Gemini only | fresh keys; BYOK users unaffected; `/health` made honest |
| Cost/abuse | each analysis ≈ 2–3 LLM calls | per-user daily cap, flag kill-switch, median of 2 not 3 if quota-tight |
| Privacy/Play policy mismatch | ✔ policy says "does not record your voice"; audience 18+ | gates in §9 — do not enable the flag before they pass |
| Long-session memory/battery on low-RAM phones | unknown | 15-min cap, chunked storage, S1 measures it |
| Prompt injection via topic/custom text | design risk | data-quoting, boundary block, output schema validation |
| Scope creep ("build the whole spec") | the spec is ~28 sections | phases + flag; Phase 1 is a complete loop on its own |

---

## 9. Policy, privacy & safety gates (must pass before `practice_room` ≠ off)

1. **Privacy policy** (`backend/privacy.html`, "How speech is handled") currently states DuSu does not record voice. Replace with, in substance: *Practice Room records your practice on your phone, keeps it on your phone until you delete it, and — to get a transcript — sends the audio directly from your phone to the AI provider you chose (e.g. Groq) using your own key; DuSu's servers do not receive or store your audio. [If the server-proxy path is used: …audio passes through our servers in memory only to be transcribed and is not stored.]* Add scores/feedback retention and deletion. Update `terms.html` and the account-deletion page.
2. **Play Data safety:** review "Audio / voice or sound recordings" and "shared with third parties" answers against Play's definitions *(verify with Play's help before answering — do not guess)*.
3. **Audience:** keep **18+** — copy says college / university / work, not school. A non-18+ audience would trigger Families-policy obligations.
4. **Recording UX:** explicit tap to start, always-visible indicator, no background recording, one-tap delete.
5. **Content safety:** persona boundary block in every Practice prompt; topic/scenario treated as data; no medical/legal advice framing in feedback.
6. **Minors:** the app states it is not directed to under-13s; no change needed, but do not market the feature to school students.

---

## 10. Success metrics (after launch)

Activation: first completed attempt within 24 h of seeing the feature · **Loop:** second attempt within 48 h ≥ 35 % · quality: share of reports rated 👍 ≥ 70 % · average improvement attempt 1→3 · D7 retention of Practice-Room users vs others · analyse success rate ≥ 97 % · p95 time-to-report < 30 s · LLM cost per attempt · recording-failure rate < 2 %.

---

## 11. Decisions needed from the owner

| # | Decision | Recommendation |
|---|---|---|
| D1 | **Record the student's voice** (on-device, with policy + Data-safety update) vs transcript-only (no replay, no Mistake Replay) | Record. The replay loop is the feature's edge; transcript-only is a different, weaker product |
| D2 | Transcription: student's own Groq key (direct) with server proxy later | Yes. Requires a Groq key for this feature (already recommended during setup); fix the server Groq key for tester/server-key users |
| D3 | Audience copy | College / university / professionals; no "school" |
| D4 | Keep full transcripts server-side? | No — scores + report only; transcript/audio on device |
| D5 | Rollout | `off` → `testers` (closed-test cohort, after spikes) → `on` |
| D6 | Event reminders | In-app banner now; no push (the TWA's reminder is a fixed 4-hourly notification) |
| D7 | Order vs the Play closed-test retry | Spikes now; don't enable for testers until S1–S3 pass and v1.2 is cut (§12) |
| D8 | Languages at launch | Hindi + Hinglish + English. Hinglish is how many students really speak and costs nothing extra (it uses the Hindi scoring column) |
| D9 | English invitation default | **On** — once per attempt, on the report, dismissible, with a permanent off switch (§13.4). Pick **Off** if Hindi students should never be nudged unless they ask |
| D10 | Daily Talk's repeated reminder (spoken after every 3rd input) | Replace it with the same dismissible card — a separate half-day change, not part of Practice Room (§13.1) |
| D11 | XP for Hindi attempts | Identical to English. Nothing should pay a student to leave Hindi — or to avoid it |

---

## 12. How this fits the Play closed-test retry

- It is the strongest answer to Google's *"did testers use all features / production-like behaviour?"* and *"changes made based on feedback"* — **if** it ships stable. A buggy new feature mid-test is worse than none.
- Sequence: run **Phase 0 spikes during the pre-flight (Oct 6–9)**; keep Day 1–4 of the test on the current feature set; release Phase 1 behind the `testers` flag as **v1.2 around Day 5–8** with an honest changelog entry; give testers a themed task ("Practise a 3-minute presentation").
- S1 results decide whether it can ride v1.2 or waits for v1.3.
- Copy the real feedback it generates into the test's feedback log.

---

## 13. Language modes — Hindi · Hinglish · English

> Added 2026-10-06 after the owner's note: *students should be able to practise in Hindi or English; some want to practise in Hindi, and DuSu keeps saying "you're doing well in Hindi — you can practise in English too"; make a solid plan.* **✔** = measured or read on 2026-10-06 (prototype on the server's Gemini key, code read, docs fetched). Everything else is design, or an *(assumption)* with a spike in §13.10.

### 13.1 Reading the request — and where today's repeated nudge comes from
The note can be read two ways: *keep that encouragement* or *stop repeating it*. ✔ What the product does today, read in code: Daily Talk (a) speaks **every** Hindi sentence back in English — "English mein aise bolte hain" plus the line in slow English (`handleDailyTurn`, `test_client.html` L4558–4562), and (b) after **every 3rd** input speaks a generic reminder — *"when you're ready you can take your learning further below — or keep talking here"* (`dailyInputs % 3`, L4571–4577). The model is not the cause: `DAILY_TURN_SYSTEM` only allows an occasional tiny English tip (`prompts.py` L353–355).

**One policy serves both readings:** Hindi practice is first-class (full credit, never second-best); DuSu offers English **once per attempt, on the report, as a dismissible card, with a permanent off switch** (§13.4). If the owner wants no nudging at all, flip the default (D9) — nothing else changes.

### 13.2 Principles
1. The student chooses the language of the talk; DuSu never overrides it.
2. A Hindi attempt earns exactly the same XP, streak, missions and badges as an English one.
3. DuSu is an English coach, so English is *offered* — at a natural moment (after a report), using evidence from the student's own talk — never imposed, never spoken aloud, never repeated.
4. Don't score what can't be scored fairly: no Hindi grammar, no Hindi "pronunciation".
5. Whatever is shown about a Hindi talk quotes or paraphrases the student's own words.

### 13.3 Setup (extends PR-2)
| Control | Options | Default |
|---|---|---|
| **I'll speak in** | Hindi · Hinglish (mixed) · English | last choice; first time English, with Hindi / Hinglish one tap away |
| **Feedback in** | Hinglish (Roman letters) · English | from the onboarding choice — `journey.lang` `hi` → Hinglish, `en` → English ✔ (`db.py` L385); if missing: Hinglish for Hindi/Hinglish talks, English for English talks |
| **English invitation after my report** | On · Off | On (D9); same switch in Settings |

Under the chips, when Hindi or Hinglish is selected: *"Hindi practice counts fully — XP, streak, everything."* Choices are stored in `memory.facts.practice_prefs` and on every attempt row (§13.8).

### 13.4 The English bridge — a Hindi → English ladder
```
Hindi attempt → Report ─► ✅ <their best strength, quoted from the analysis>
                         "Ab isi talk ko English mein bolke dekhein?"   [Try in English]  [Not now]
                                          │ tap
                                          ▼
          Bridge sheet (built in 2–3 s): outline — each of YOUR points → one simple English sentence · 6 key phrases
          (English + Hindi meaning, 🔊 slow) · an opening line · a closing line
                                          │ [Record in English]  (same topic and time; the outline is hidden behind "Peek" — peeks are counted)
                                          ▼
          English report  +  "Same talk, two languages": Content · Structure · Time · Steadiness side by side;
          Grammar · Vocabulary · Clarity shown as "new in English — your baseline" (never as a drop)
```
**Nag guard — the actual policy**
- The card appears only on the report of a Hindi/Hinglish attempt that counts (`genuine_effort`) and has at least one strength. Never during practice, **never spoken (no TTS)**, never after an English attempt.
- At most once per topic per day. "Not now" twice in a row → snoozed for 14 days. A small "Don't show again" turns it off for good (reversible in Settings).
- The card is **static UI copy plus `strengths[0]` from the analysis** — no extra model-written praise. ✔ A model-written invitation called a 66-point talk "bohot clear"; building it from scored strengths removes that failure by construction.
- Success measures (proposed): invitation opened ≥ 20 %; "Don't show again" ≤ 30 % (if more students switch it off, the card is too pushy — show it less).
- The bridge is a **separate on-demand call** (`POST /practice/bridge`): students who ignore the card cost nothing. ✔ Prototype (Gemini flash-lite): 5–6 outline points per talk in 2–3 s, and for a deliberately thin ~50-word Hindi talk **0 invented terms** (the prompt says "use only what they said").

### 13.5 Transcription for Hindi and Hinglish
- ✔ Groq docs: `language` is ISO-639-1 (`hi`); `prompt` ≤ 224 tokens; `timestamp_granularities[]` word / segment; two models — `whisper-large-v3-turbo` (transcription only) and `whisper-large-v3` (also translation), which Groq describes as the higher-accuracy one. Rate limits for the non-turbo model are **not** checked yet.
- Default: English → `en`; Hindi → `hi`; **Hinglish → `hi`** *(assumption)*. S2b picks between: turbo vs `whisper-large-v3` · with / without a short mixed-script prompt (e.g. "आज हम AI in healthcare के बारे में बात करेंगे।") · `en` for Hinglish · auto-detect.
- Hindi output is expected in Devanagari, probably with English loanwords also in Devanagari *(assumption — search snippets only; the one page I fetched did not confirm it)*. The analysis prompt reads both scripts ✔ (a Devanagari talk and a Roman-script Hinglish talk both scored sensibly), and quote checks must ignore script variants and punctuation (NFC, strip punctuation, case-fold) ✔ — on quoted grammar fixes, 6 of 6 matched after normalising versus 5 of 6 exactly.
- ✔ A third-party model card ([BuzzASR/hindi](https://huggingface.co/BuzzASR/hindi), secondary source) lists zero-shot Whisper-large-v3 on Hindi at **character** error 9.3 % (FLEURS) / 12.5 % (Common Voice 25) on read speech; it gives no word-error figure, and real student audio is noisier. Treat Hindi transcripts as less reliable than English: the prompt tolerates recognition glitches; segments with low Whisper confidence are marked "unclear audio" and never counted as mistakes; the student can read the transcript; "edit and re-score" is a Phase 2 item.

### 13.6 Scoring by language
| Category | English | Hindi / Hinglish | Why |
|---|---:|---:|---|
| Fluency | 20 | 25 | pauses, restarts, hesitation from word timestamps — language-neutral. **Pace points: English only** until S3b sets Hindi bands (no invented wpm range) |
| Content | 20 | 30 | LLM, with quoted evidence |
| Structure | 10 | 15 | LLM booleans and counts |
| Steadiness | 10 | 15 | pace *variance* (relative, so language-neutral) + restarts + LLM |
| Time | 10 | 15 | measured |
| Grammar | 15 | — | English only: Hindi transcripts are machine-normalised, and DuSu is not a Hindi coach |
| Vocabulary | 5 | — | English only |
| Clarity | 10 | — | English only: for Hindi it would mostly measure the recogniser, not the speaker |
| **Total** | **100** | **100** | |

- Hinglish uses the Hindi column. English terms inside Hindi are never penalised; the copy says "Hinglish is valid".
- **No filler counts for Hindi/Hinglish** — *matlab / toh / haan* are ordinary discourse markers. Show restarts and unfinished sentences instead. "You said / Better" fixes are English-only; DuSu does not correct Hindi.
- **Fairness ✔** — the same strong talk written in Hindi and in English, 3 runs each, temperature 0.2: fluency 92/92, content 90/90, structure 94/95, steadiness 90/90 → **mean 91.5 Hindi vs 91.8 English**. Weak talks were only compared within a language (Hindi 54–55, English 49–60), so S3b repeats the parity test on weak talks with real students.
- **Noise ✔** (LLM-judged part only; n = 3–5 per talk, indicative): spread Hindi strong 0 · Hindi weak 1 · Hinglish 3 · English strong 0 · English weak 11. The wobble sits in English grammar/vocabulary judgement, which Hindi scoring doesn't use.

### 13.7 Three traps in the existing Speaker Progression code (read ✔, fix in Phase 1)
1. **An unknown mode is logged as "conversation".** `award_speaker_progress` does `mode = mode if mode in _MODE_BONUS else "conversation"` (`db.py` L705). Without the §6 additions, a Practice attempt would count as Face-to-Face and feed `fearless_speaker` / `conversation_builder` (`db.py` L859–860).
2. **Missing components become zeros.** `overall = 0.30·confidence + 0.25·continuity + 0.20·vocabulary + 0.15·grammar_trend + 0.10·depth`, and `_clamp100(None)` returns 0 (`db.py` L726–728, L671–675). A Hindi attempt has no vocabulary or grammar, so 35 % of the weight would silently vanish and the attempt would look like a regression in "delta vs your last 5" (L812–817) and Before-vs-Now (L1033+). **Fix (B7a):** renormalise `overall` over the components that were scored and store NULL for the rest — `ALTER TABLE session_scores ALTER COLUMN vocabulary DROP NOT NULL, ALTER COLUMN grammar_trend DROP NOT NULL` (idempotent) plus `Optional[int]` in the model. The only reader of those two columns is the response payload (`db.py` L829–830); the client never reads them by name — it only forwards `sp.scores` to `/confidence-check/save` (`test_client.html` ~L4181), and Practice Room attempts never enter Confidence-Check mode. Existing callers always pass all five scores, so their behaviour is unchanged.
3. **Mapping:** confidence ← steadiness, continuity ← fluency, depth ← content; vocabulary ← vocabulary and grammar_trend ← grammar for **English attempts only**.

XP formula, caps and streak rule are identical for every language. The new badge **Bridge Builder** (finished a Hindi → English pair) carries no XP, so nothing pays a student to leave Hindi.

### 13.8 Data
`practice_attempts` gains `lang` (`en` / `hi` / `hinglish`), `feedback_lang`, `via` (`direct` / `bridge`) and `invite` (`none` / `shown` / `opened` / `dismissed`); the planned `parent_id` links an English attempt to its Hindi source. `memory.facts.practice_prefs = {lang, feedback_lang, english_invite, invite_dismissals, invite_snooze_until}` — JSONB, no migration; writes go through `_get_or_make_memory`, which row-locks. Both are covered by the deletion work (B8). Another Indian language later = one more `lang` value and one prompt row, not a redesign.

### 13.9 Work added (estimates, not measurements)
| Item | What | When | Est. |
|---|---|---|---|
| **B0** | Harden `_extract_json` (below) — helps every JSON endpoint, not just this one | before Phase 1 | 0.5 d |
| B3′ / B4′ | Language-aware prompt (Appendix D) and per-language weights | Phase 1 | +1 d |
| **B7a** | Nullable components and renormalised `overall` (§13.7) | Phase 1 | +0.5 d |
| F2′ / F7′ | Language and feedback chips, prefs; report variant that hides Grammar / Vocabulary / Clarity for Hindi | Phase 1 | +1 d |
| B10 / F12 / F13 | `/practice/bridge`, bridge sheet, side-by-side comparison, Bridge Builder badge | Phase 1b | +2 d |
| D10 | *(separate)* Daily Talk: swap the spoken every-3rd-turn reminder for the same dismissible card | any time | 0.5 d |

**B0 — measured ✔.** 4 of 36 Gemini-lite JSON replies this session (11 %) failed to parse: 2 of 10 with the big "bridge inside the analysis" prompt, 2 of 26 with the slim prompts. The cause is **not** truncation (`finish_reason=stop`, ~190 tokens). One captured reply closed the root object early and kept writing (`…}]}` then `"genuine_effort":true}`); another had a stray closing brace. Today's `_extract_json` (`json.loads`, then a greedy `{…}` regex) fails on both. A parser that takes the first complete object (`raw_decode`) and merges any trailing `"key": value` pairs recovered both shapes offline and left every input the current parser already handles unchanged; genuine truncation still fails, as it should. **Consequence:** a repaired reply can lose its tail, so every gating field (`genuine_effort`, minimum words) must also be computed server-side, with the model's flag only able to *lower* trust.

### 13.10 Spikes added to §7
| ID | Question | Pass when |
|---|---|---|
| S2b | Hindi / Hinglish transcription on real phones: 10 Hindi + 10 Hinglish + 10 English clips, ≥ 5 speakers, **read from a script** so error rates can be computed; the config matrix in §13.5 | usable transcript on ≥ 85 % of clips and ≤ 15 % character error against the script *(proposed bar — tune after seeing data)*; winning config recorded |
| S3b | Per-language golden set (10 Hindi + 10 Hinglish transcripts at three quality levels × 5 runs); parity set — the same talk by the same students in Hindi and in English; Hindi pace bands from real recordings | σ ≤ 2.5; parity gap ≤ 5 points; pace bands set from data |
| S6 | English-invitation policy on the `testers` cohort | opened ≥ 20 %; "Don't show again" ≤ 30 % |

### 13.11 Risks specific to language
| Risk | Evidence | Mitigation |
|---|---|---|
| Hindi recognition errors lower content/structure scores unfairly | ~9–12 % character error on clean read speech (secondary) | tolerance clause in the prompt; low-confidence segments excluded; S2b; edit-and-re-score later |
| Whisper mis-detects, or "translates", Hinglish | unknown | `language` always set explicitly; S2b config matrix |
| Quote checks fail across scripts | ✔ 5 of 6 exact → 6 of 6 normalised | normalised matching; a quote that can't be found is dropped, never shown |
| Praise inflation on weak talks | ✔ a model-written line called a 66-point talk "bohot clear" | card built from scored strengths; "no intensifiers below 80" rule in the prompt (still untested) |
| Language choice changes the score | ✔ strong-talk parity 91.5 vs 91.8 | S3b parity test on weak talks and real students |
| A Hindi attempt drags the Performance trend down | ✔ code read (§13.7) | B7a |
| The server's free Gemini key can't carry analysis for many users | ✔ a 24-call burst (6 at a time) returned `429 RESOURCE_EXHAUSTED` on 8 | BYOK-first; analysis is cheap (≈ 170–400 output tokens, 2–4 s) when the bridge is a separate call |

### 13.12 Phase 2 modes (Viva, Discussion)
Same two chips. The examiner asks and answers in the chosen language and never switches mid-session; there is no Daily-Talk-style English echo. Live turn-taking can use the `hi-IN` recognition and `HI()` voice that Daily Talk already ships (✔ in code), so Hindi viva does not depend on the Whisper spike. Viva scoring stays language-neutral (knowledge, answer structure, response time); English accuracy is scored only in English sessions.

---

## 14. Implementation status — built 2026-10-06 (dark: nothing is visible until the owner flips the switch)

**What exists** — Phase 1 + 1b (the English bridge) + the §13 language modes:

| Area | Where |
|---|---|
| Switch | `settings.practice_room` = `off` (default) / `owner` / `on`; More → Dashboard → Access → Practice Room; the client sees it as `/me.practice_room` |
| Scoring module | `backend/app/practice.py` — measured metrics (pace, pauses, restarts, pace variance, time, recogniser confidence), per-language weights, quote verification, median of `RUNS = 2`, comparison with a 5-point noise floor, the English-invitation nag guard, the bridge |
| Prompts | `interview/prompts.py` — `practice_analysis_system()` / `practice_bridge_system()` (Appendix D plus per-category notes, content gaps, hard words, the shared boundary block, topic and transcript wrapped as data, a "no intensifiers below 80" praise rule) |
| Endpoints | `POST /practice/analyze` · `/practice/bridge` · `/practice/prefs` · `/practice/delete` · `/practice/transcribe` (server proxy, only for accounts on DuSu's own keys) · `GET /practice/history` · `/practice/attempt` |
| Data | new table `practice_attempts`; `session_scores.vocabulary` / `grammar_trend` made NULLable (idempotent migration in `init_db`); preferences in `memory.facts.practice_prefs`; deletion paths (B8) cover the new table |
| Progression | Practice kinds in `_MODE_BONUS`; `award_speaker_progress(..., unscored=)` renormalises `overall` (B7a); badges First Presentation / 10 Presentations / 80+ / 90+ / **Bridge Builder** (no XP); weekly missions, league, streak, companion memory line and the optional "when is it?" Home banner all ride the existing pipeline |
| Hardening | `_extract_json` repairs both broken-brace shapes (B0); `_complete(..., temperature=)` (B2); transcripts never logged (`_safe_err`) |
| Client | `test_client.html` — hub, setup (language, feedback language, level, goal, date, invitation switch), live recorder (MediaRecorder, IndexedDB chunk mirror, Wake Lock, auto-pause, level meter, 15-minute cap), Groq transcription straight from the phone, resumable pipeline, report (bars, deltas, tap-to-seek transcript with audio, 🔊 on fixes/words), the one-card English invitation, the bridge screen with Peek, per-account takes wiped on account deletion; `sw.js` v18 |
| Policy | `privacy.html`, `terms.html`, `account-deletion.html` rewritten for audio (§9 gate 1) |

**Deviations from this plan**
- Rollout tiers are `off / owner / on`. A `testers` tier was left out: the settings value column is 255 characters, too small for an email list. `owner` is the vehicle for the Phase-0 phone spikes.
- `RUNS = 2` analysis runs, not 3 — the free provider keys are the constraint (a 429 on one provider cools it down for everyone). Raise `practice.RUNS` once quota allows.
- Hinglish is sent to Whisper as `language=hi` (assumption until S2b); no mixed-script prompt yet.
- Only the Presentation type is live; Viva / Discussion / Speech / Seminar / Custom show "Soon" (the schema and XP table already accept them).
- Pace points are English-only (no Hindi wpm bands until S3b); no "edit transcript and re-score", no Mistake Replay (Phase 2).
- The Daily Talk reminder (D10) is **not** changed.

**Verified on 2026-10-06**
- *Backend — 57 checks, HTTP level, real model, scratch Postgres on the host (never production):* the OLD schema was created with the currently deployed code, then the new `init_db` was run twice (migration + idempotence); flag off/owner/on and the BYOK gate; an English talk (8 categories, scored 90), a Hindi talk (5 categories, vocabulary/grammar stored as NULL, `overall` renormalised), the bridge, the English attempt that follows it (`via=bridge`, language-neutral deltas, Bridge Builder), retry deltas, the nag guard (two "Not now" → 14-day snooze), prefs allow-list, history / re-open / delete (children re-parented), pruning, oversized input, the transcribe proxy's error paths, account deletion removing attempts. A first run caught a real bug (SQLAlchemy turned an explicit `None` into the column default `0`); fixed and re-run clean.
- *Browser — 87 checks in Chromium with a fake microphone (real MediaRecorder + IndexedDB + AudioContext), new endpoints and Groq stubbed, no server writes:* flag-off changes nothing; setup chips; countdown, pause, auto-pause on backgrounding, leave-guard; transcription goes to Groq with the student's own key; report for English and Hindi; invitation card (never spoken; "Not now" / "Don't show again" reach the server); bridge → English attempt; failure states keep the take; a crash mid-recording is recovered from IndexedDB; a second account on the same phone cannot see the first account's take; desktop two-column layout. Two bugs found and fixed on the way (the recorder never left its "idle" state; `AudioContext.resume()` could block Start).

**NOT verified — needs the owner's phone / real audio**
- S1: recording inside the TWA (permission prompt, Wake Lock, interruptions, battery) on Redmi / Realme / Samsung.
- S2 / S2b: real Whisper accuracy on Indian-accented English, Hindi and Hinglish; the config matrix of §13.5.
- S3 / S3b: score calibration and Hindi↔English parity on real student speech.
- `/practice/transcribe` with a working server Groq key (the current one returns 401).

**Before the switch goes past `owner` (§9 gates)**
1. Play Console → Data safety: re-answer "Audio / voice recordings" and "shared with third parties" (the pages now describe the flow; the form must match — check Play's own definitions before answering).
2. Play audience stays 18+; copy says college / university / work.
3. Replace the dead server Groq key if accounts on DuSu's own keys should transcribe.
4. Run S1–S3 on a phone with the switch on **Owner only**, then flip to **Everyone** (or keep it dark for the closed test — §12).

---

## Appendix A — Draft analysis prompt v0 (prototype-tested)

```
You are DuSu's presentation coach for Indian college students. You analyse ONE spoken practice transcript.
The transcript came from speech-to-text: ignore punctuation, capitalisation and tiny recognition glitches; never penalise spelling.
Score each skill 0-100 with these anchors: 90+ excellent for the level; 75 good, small issues; 60 understandable but frequent issues;
40 hard to follow; under 25 almost nothing usable. Be consistent and evidence-based, not generous.
Return ONLY a JSON object:
{"scores":{"fluency":int,"grammar":int,"vocabulary":int,"content":int,"structure":int,"steadiness":int},
 "structure_check":{"introduction":bool,"main_points":int,"examples":int,"conclusion":bool},
 "strengths":[up to 3 short strings],
 "improvements":[up to 3 {"issue":str,"how":str}],
 "grammar_fixes":[up to 3 {"said":"EXACT words from the transcript","better":str}],
 "genuine_effort":bool}
If the transcript has fewer than 40 words set genuine_effort false.
```
**Prototype result ✔:** valid JSON 9/9 runs; `grammar_fixes` quoted the speaker exactly (3 real errors from the weak sample) and returned none for the strong sample run I inspected (no false positive seen); ~3.5 s per call. **To add for v1:** a conclusion must summarise/wrap up (not just "thank you"); `hard_words`; evidence quotes for content gaps; the boundary block; topic/scenario wrapped as data.

## Appendix B — Spec → plan traceability (the spec's own 16-item MVP)

| Spec MVP item | Here |
|---|---|
| 1 Select Presentation · 2 topic · 3 duration | F1, F2 |
| 4 Start / 5 stop recording · 6 save recording | F3, F4, F9 |
| 7 Transcript | F5, F7 (Whisper) |
| 8 Overall score · 9 Fluency · 10 Grammar · 11 Pronunciation · 12 Content · 13 Structure | B4/B3, §4.2 (Pronunciation → **Clarity**) |
| 14 Listen to recording | F7, F9 |
| 15 Basic improvement suggestions | B3 (strengths / fixes / next step) |
| 16 Practice again | F7 + **attempt comparison pulled in** (F8) |
| Spec Phase 2: Viva, Discussion, Custom, comparison, Mistake Replay, dashboard | Phase 2 (comparison moved to Phase 1) |
| Spec Phase 3: weekly report, streaks, achievements, goals, templates | Phase 3 — mostly *reuse* of Speaker Progression |

## Appendix C — Evidence behind the numbers (2026-10-06)

- Scoring noise: §4.3 (Gemini `gemini-flash-lite-latest`, 3 runs per condition).
- Groq Whisper CORS: preflight from `https://dusu.ranabrothers.online` → `access-control-allow-origin: *`; unauthenticated call → 401 (endpoint alive).
- Server providers (one 8-token call each): Groq 401, OpenRouter 404, GitHub dead, Gemini OK.
- Client has no `MediaRecorder` / `getUserMedia` / Wake Lock / IndexedDB.
- Privacy policy and Play audience text: `backend/privacy.html` ("How speech is handled"), `PLAYSTORE_SUBMISSION_GUIDE.md` §8.
- Web sources (secondary — verify before relying): Web Speech continuous-mode and Android reliability reports ([W3C speech-api list](https://lists.w3.org/Archives/Public/public-speech-api/2015May/0000.html), [Web Speech API issue #96](https://github.com/WebAudio/web-speech-api/issues/96)); Groq free-tier audio limits ([free-llm.com](https://free-llm.com/models/groq-cloud/whisper-large-v3-turbo), [toolfreebie.com](https://toolfreebie.com/?p=237)). Android Chrome behaviour when SpeechRecognition and MediaRecorder run together: **no authoritative source found** — hence S4/S1.
- Language work (2026-10-06): prototype on the server's Gemini key (`gemini-flash-lite-latest`, temperature 0.2) — 36 JSON replies across five talks (Hindi strong / weak, Hinglish, English strong / weak); results in §13.6 and §13.9. The scripts live only in the session scratchpad, not in the repo.
- Groq speech-to-text parameters, models and limits: [Groq docs](https://console.groq.com/docs/speech-to-text).
- Hindi recognition accuracy: [BuzzASR/hindi model card](https://huggingface.co/BuzzASR/hindi) — zero-shot Whisper-large-v3 **character** error 9.28 % (FLEURS), 12.52 % (Common Voice 25), 11.92 % combined; no zero-shot word error is reported and the normalisation is not stated. *A first web-search summary attributed a 36–40 % word error to zero-shot large-v3; the card's table shows those figures belong to the fine-tuned model, so they are not used here.*
- Whisper on Hinglish: [Trelis write-up](https://trelis.substack.com/p/whisper-hinglish) describes a fine-tuned mixed-script model and does not report baseline Whisper behaviour — the "loanwords come out in Devanagari" expectation stays an assumption.

## Appendix D — Language-aware prompts v1 (prototype-tested 2026-10-06)

**Analysis** — one template; `<<LANG>>` is `Hindi`, `Hinglish (Hindi + English mixed)` or `English`. Text in [brackets] applies to one language group only.
```
You are DuSu's presentation coach for Indian college students. The student practised a talk in <<LANG>>.
The transcript came from speech-to-text: ignore punctuation, spelling and script (Devanagari or Roman). Never penalise colloquial or dialect speech, or English technical terms mixed into Hindi.
Score each skill 0-100 with these anchors: 90+ excellent; 75 good, small issues; 60 understandable but frequent issues; 40 hard to follow; under 25 almost nothing usable. Be consistent and evidence-based, not generous.
Judge: fluency (smooth connected sentences, no endless restarts), content (covers the topic, explains, gives examples), structure (introduction, main points, an example, a REAL conclusion - a bare 'thank you' is not a conclusion), steadiness (few hesitations, restarts, unfinished sentences)[English only: , vocabulary (clear, precise, varied words for a college student), grammar (sentence correctness)].
Write ALL feedback text in simple Hinglish (Hindi written in Roman letters), warm and specific. Each strength and improvement must point at something the student actually said.   [for "Feedback in: English": "...in simple English (short sentences)..."]
[Hindi / Hinglish only: Do not judge or correct Hindi grammar or spelling - the transcript is machine-generated and unreliable for that. Judge only the four skills listed.]
Return ONLY a JSON object:
{"scores":{"fluency":int,"content":int,"structure":int,"steadiness":int[English only: ,"vocabulary":int,"grammar":int]},
 "structure_check":{"introduction":bool,"main_points":int,"examples":int,"conclusion":bool},
 "strengths":[up to 3 short strings],"improvements":[up to 3 {"issue":str,"how":str}],
 [English only: "grammar_fixes":[up to 3 {"said":"EXACT words from the transcript","better":str}],]
 "genuine_effort":bool}
If the transcript has fewer than 40 words set genuine_effort false.
```
**Bridge** — a separate call, made only when the student taps "Try in English":
```
You help an Indian college student move a talk they just gave in <<LANG>> into English.
Use ONLY what the student actually said. Do not add facts, examples, numbers or opinions they did not say. If they said little, produce little.
Write simple spoken English (B1: short sentences, words a student already knows).
Return ONLY a JSON object:
{"outline":[{"point":"<their point in 6 words or fewer, Hinglish in Roman letters>","say":"<one simple English sentence they can say>"}],
 "key_phrases":[{"en":"<useful English phrase taken from THEIR content>","hi":"<meaning in Roman Hindi>"}],
 "opening":"<one English sentence to open the talk>","closing":"<one English sentence to close it>"}
outline has 3 to 6 items in the order they spoke; key_phrases has 6 items.
```
**Prototype results ✔** (Gemini flash-lite, temperature 0.2): analysis replies 170–400 output tokens in 2–4 s (the earlier version with the bridge inside took 12–17 s); bridge replies 200–280 tokens in 2–3 s. **Still to add for v1:** a "no intensifiers (bahut, shaandar, excellent …) about a skill scored below 80" rule — not yet tested (the planned run was dropped when the invitation moved to scored strengths); `hard_words` for English; the shared boundary block; topic/scenario wrapped as quoted data; and `temperature` 0.2, which needs B2.

# DUSU Speaker Progression — Product Spec v1.0.3 — IMPLEMENTATION BASELINE

> **✅ PHASE 1 IMPLEMENTED (2026-08-19).** All 8 frozen Phase 1 items (§7b) + both locked §9 latency fixes are built and verified against the real DB and real LLM providers — not just written. One real bug was found and fixed during verification (`delete_user`/`admin_wipe_users` didn't know about the two new tables — now do). Full implementation-vs-plan compliance report delivered in-conversation; not duplicated into this file. Phase 2/3 items remain correctly unbuilt, per §7b's frozen boundary.

> **✅ PHASE 2 IMPLEMENTED (2026-08-19).** All 7 Phase 2 items built and verified live: tiered streak badges, Achievement Gallery + `check_achievement_badges()`, milestone-gated Speaker Rank (`_RANK_MILESTONES`), rules-based personalized Weekly Missions, adaptive Interview difficulty (CEFR level + past-performance trend + stated career goal), a deeper Confidence Check (full history, not just last-vs-previous), and a deeper Before-vs-Now (a real chronological timeline, not two snapshots). One real bug was found and fixed during verification: `SeasonAward`'s primary key was initially `(user_id, season_id)`, which crashes the moment a single user leads more than one award category in the same season — corrected to `(season_id, award_key)` before it ever reached prod.

> **Phase 3 (2026-08-19): implemented what's real, explicitly skipped what isn't yet.** Built: 6-Month Speaker Awards (new `SeasonAward` table, owner-triggered `compute_season_awards()` batch — no cron on this stack — one winner per category, `/admin/compute-season-awards`), a shareable text card for season awards (reusing the existing `navigator.share`/clipboard pattern — no image-generation infra exists, so this is text, not a graphic), and a seasonal Home banner (`renderSeasonBanner()`, dismissible per award). **Deliberately NOT built: friends/country leaderboards (item 19).** §18 item 7 locks that "out of scope until retention data justifies it" — one day post-Phase-1-ship there is zero retention data, so building it now would contradict the lock rather than satisfy it.

> **✅ FULL-SYSTEM AUDIT + FIXES (2026-08-22).** Three independent skeptical audits (data layer, API/engine/prompts, frontend) re-read this doc and the real code fresh — not trusting the banners above — then every claim was cross-checked against the actual plan text before acting. Real bugs found and fixed: `genuine_effort` defaulted to `true` on LLM parse failure instead of the locked `false` (main.py); Journey lesson XP never fed Speaker XP despite §5's explicit table row (`complete_lesson` in db.py); the `mission_progress` WS message was sent server-side but had no client handler, so mission completions never surfaced (test_client.html); Confidence Check's first-ever check returned `delta:null` instead of comparing to the Day-1 baseline per §2.2 (`save_confidence_check`); Before-vs-Now returned `{}` with <7 days of history instead of falling back per §2.2 (`speaking_trend`); §14 Personal Best was missing 2 of its 4 locked sub-metrics (best confidence, best weekly minutes — now `personal_best()`); the post-session League rank delta (`_global_rank`) used a 3-level tie-break while the real League screen correctly used 4, so they could silently disagree on an exact tie — unified; the "AI-estimated" disclaimer (§13, locked "applied everywhere") was missing from the Interview report and the Confidence Check history list — added. Also fixed along the way: `access_phase` was set to `"growth"` (forces BYOK on everyone) when the intent was open beta testing — flipped to `"quota"`, and the free-tier cap raised from 5→500 req/day. One audit claim was checked and rejected: a "missing 5-component score breakdown UI" citing the anti-casino rule — verified the anti-casino rule (§12) is about animation *frequency*, not a score-breakdown UI; no such requirement exists in the doc. Full live E2E re-run after fixes (real HTTP + WebSocket + real LLM calls, all 4 modes) — all checks pass, including the critical speaker_progress-before-ended ordering confirmed over the real wire, not just by reading code.

> **A sixth review pass called v1.0.2 ~98-99% implementation-ready and found exactly 3 remaining fixes — not another planning round.** All 3 closed in this revision (v1.0.3): `WeeklyStat.xp_reached_at` added as a real column (the tie-break rule in §6 referenced a timestamp the schema didn't actually have — caught correctly); `thoughts_translated` given an explicit place in the post-session content order, Daily Talk only (§7); and the parse-failure XP behavior in §20 rewritten precisely — `genuine_effort=false` still earns 0.3× XP via the existing §2.1 formula (participation preserved), it just contributes to no Performance trend (was ambiguous before, correctly flagged).
>
> **This is now the implementation baseline.** No further planning pass is expected before Phase 1 work starts — per the last review, backend/data-layer implementation can proceed directly from this document; UI mockups refine the frontend afterward against the already-locked design system (§12), they don't gate starting.
>
> History: v1 → v2 (schema/latency/color) → v3 (full product plan) → v1.0 (every open decision + formulas + Phase 1 boundary + success metrics locked) → v1.0.1 (operational specificity) → v1.0.2 (5 engineering-correctness gaps closed) → v1.0.3 (this revision: the last 3 small fixes a sixth review found; declared the implementation baseline).

---

## 1. Vision & core loop (revised)

Not: *"Add gamification around English practice."*

**"Turn every conversation into measurable progress, and turn measurable progress into a reason to return."**

**SPEAK → MEASURE → IMPROVE → REWARD → RANK → IDENTITY**

The user should never just see a number. Every number needs a *because* and a *next*:

> ❌ "You spoke 42 minutes this week."
> ✅ "You spoke 42 minutes → your confidence improved 8% → you moved from #31 to #18 → you're 24 XP from Top 15."

That chain — measured, explained, ranked, given a next target — is the actual hook. Every surface this plan touches (post-session screen, Home, League) should try to say all four parts, not just the raw stat.

---

## 2. XP vs. Performance — two separate concepts, on purpose

This is a correction from v1, and it matters enough to be its own section: **do not let "more talking" alone mean "better English."**

| | **Speaker XP** | **Speaking Performance** |
|---|---|---|
| Measures | Participation & progression | Actual skill development |
| Drives | Speaker Rank, League position, missions, rewards | Confidence Check deltas, Before-vs-Now, "what to improve" |
| Source | Minutes spoken, sessions completed, missions done, streaks | Confidence, continuity, vocabulary, grammar trend, depth (per-session scores) |
| Can be gamed by just showing up? | Yes, by design (that's what participation currency is for) | No — it's a model-scored assessment of quality, not a counter |

Both matter, but they answer different questions. XP answers "are you showing up?" Performance answers "are you actually getting better?" A user who talks 10 hours of low-effort chat should rank up on participation but should **not** see their Confidence/Performance numbers move — that honesty is what makes the Performance side trustworthy, which is what makes Before-vs-Now and Confidence Check land emotionally instead of feeling like more fake gamification.

---

## 2.1 XP formula — locked

Not "TBD when we code it" — frozen now so Daily/Interview/Face-to-Face XP amounts are comparable on day one instead of feeling arbitrary later.

```
session_xp = floor(minutes_spoken × 10) + mode_bonus
session_xp = min(session_xp, 300)                    # per-session cap (anti-gaming §13)
session_xp = session_xp × effort_multiplier          # 1.0 normal, 0.3 if genuine_effort=false, 0 if turns<=0 (existing guard)
daily_total_xp = min(sum of today's session_xp, 600)  # per-day cap across all sessions (anti-gaming §13)
```

**Allocation semantics, locked**: the 600 cap applies to XP actually *awarded*, not computed-then-clamped-for-display. Each session is credited `min(session_xp, 600 − xp_already_awarded_today)` at the moment it ends — so three 280-XP sessions in one day award 280 + 280 + 40, not 280 + 280 + 280 with the total merely *shown* as 600. This keeps the database and every UI that reads XP always in agreement, since nothing ever needs to re-derive "what actually counted" after the fact.

| Mode | `mode_bonus` | Why |
|---|---|---|
| Daily Talk | +10 | Lowest-pressure mode — small flat bonus keeps it worth doing daily without out-earning higher-effort modes |
| Face-to-Face | +15 | Real unscripted speaking — the confidence arena, valued above Daily Talk |
| Interview | +25 | Highest cognitive load (structured pressure, competency coverage) — earns the most per session |
| Journey (lesson) | flat `XP_PER_LESSON = 20` | **Unchanged, existing constant** — lessons don't use the minutes-based formula at all, they keep their existing flat award |

10 XP/minute is chosen to sit in the same density as the existing lesson economy (a ~2-3 minute lesson already awards 20 XP today, i.e. ~7-10 XP/min) — new XP doesn't feel like a different currency next to old XP.

Non-session XP stays exactly as it already works: mission completion `+100` per mission, `+200` bonus for clearing all of a week's missions, achievement unlock XP amounts set per-badge at implementation time (small, one-time, not recurring).

---

## 2.2 Speaking Performance formula — locked

Performance is a **rubric judgment**, not a hard count — there's no arithmetic formula for "confidence," only a defined method for how the single number is produced and compared, which is what actually needs locking:

- **Per-session components** (0-100 each): `confidence`, `continuity`, `vocabulary`, `grammar_trend`, `depth` — produced once per session by the piggybacked `SESSION_MEMORY_SYSTEM` call (§6/§9), same call for every mode.
- **`overall`** (shown as "your score" wherever a single number is needed): `overall = round(0.30×confidence + 0.25×continuity + 0.20×vocabulary + 0.15×grammar_trend + 0.10×depth)`. Confidence weighted highest — it's DuSu's actual stated promise ("Speak with Confidence"); grammar and depth weighted lowest — deliberately, since correctness-policing isn't the product's job (existing interview/conversation prompts already explicitly avoid correcting grammar mid-session).
- **Session-level delta** (post-session screen, e.g. "Confidence +2%"): this session's component **minus the average of the same component over the user's last 5 sessions** (not vs. the single previous session — one bad or great session shouldn't swing the shown delta wildly).
- **Confidence Check delta**: this check's score **minus the previous check's score**, or vs. Day-1 baseline if it's the user's first check.
- **Before-vs-Now delta**: average of the last 7 days' sessions vs. the first 7 days on record (or Day-1 baseline literal text/score if fewer than 7 days exist yet).
- Interview keeps its own full, separately-weighted `SCORER_SYSTEM` rubric exactly as it exists today — that's a bigger, interview-specific report, not replaced by the 5-component Performance score (Interview produces both).
- **Low-effort sessions are excluded from every trend/average above, not just XP-reduced.** A session with `genuine_effort = false` still gets scored and stored (for the record), but is skipped when computing the session delta, the Before-vs-Now averages, and the Confidence Check comparison history. §2's whole premise — that Performance has to be trustworthy, not gameable — falls apart if a handful of "yes"/"okay" sessions can drag a real trend line around. Confidence Check itself doesn't need this filter separately: it's a deliberate, structured 2-minute check, not a casual session, so it isn't subject to the same low-effort gate to begin with.

### What each component actually measures — locked, so the model has a fixed rubric instead of a free hand

This is the piece that was still missing: weights and comparison math were locked, but not what "confidence = 72" is actually supposed to represent. Each is graded from the session transcript only (no separate signal source — no audio analysis, no timing data DuSu doesn't already have):

| Component | What raises it | What lowers it |
|---|---|---|
| **Confidence** | Complete sentences; elaborating without being asked twice; stating opinions/answers directly | Frequent one-word/fragment replies; heavy hedging ("I don't know," "maybe," excessive "I think"); giving up on a thought mid-sentence |
| **Continuity** | Sustaining one topic/exchange across multiple turns before it needs a rescue; multi-sentence turns | Needing DuSu to repeatedly re-open or rescue the same topic; frequent one-word turns that stall the exchange |
| **Vocabulary** | Range and appropriateness of word choice relative to the user's own stated English level (Journey level / onboarding CEFR) — variety, not raw word count | Heavy repetition of the same basic words when more varied ones would fit; vocabulary far below their stated level |
| **Grammar trend** | Correct sentence construction *this session* — an assessment, not a correction (DuSu still never corrects mid-session, per the existing product rule) | Frequent structural errors that a same-level speaker wouldn't typically make |
| **Depth** | Going beyond a surface fact to a reason, example, or reflection when the conversation escalates there (§11's depth-escalation rule) — this component is literally "did the escalation work" | Staying at surface-level facts even after DuSu asks a deeper follow-up |

This rubric is what gets written into the extended `SESSION_MEMORY_SYSTEM` prompt at implementation time (§20's "not covered yet" item) — locking the meaning now means that prompt is a translation of this table, not a fresh design decision made at code time.

---

## 3. Current state audit (unchanged from v1, still accurate)

| Already built | Where | Gap vs. the vision |
|---|---|---|
| XP, coins, streak_days, badges, journey | `Progress` table (`db.py`) | XP only awarded for lesson completions and Daily Talk. **Conversation and Interview earn zero XP today.** |
| All-time global leaderboard, private aliases | `db.leaderboard()` | All-time, not weekly; alias-based, not real names — a deliberate existing privacy choice (§18 decision). |
| 7-level curriculum, named Worlds, 35 lessons, boss tests | `CURRICULUM` (client), `_WORLD_NAMES` (`db.py`) | Stays untouched — see §4, Option C. |
| Badges (`first_lesson`, `streak_7`, `courage_*`, etc.) | `BADGE_LABELS`, `award_badges()` | Achievements extend this, not replace it. |
| Relationship stages (Guest→Companion), invisible | `_REL_STAGES` (`db.py`) | Separate axis, keep separate. |
| Full scored report (grammar/fluency/confidence/...) | `SCORER_SYSTEM`, Interview only | The Performance rubric this plan needs for ALL modes already exists for one. |
| Before/Now data already collected (`baseline.intro_text`, `future_me`, `build_growth()`) | `db.py` | UI/presentation gap, not a data gap. |
| Post-session report screen | Interview only | Conversation & Daily Talk have no session-end screen at all — **the single biggest missing piece.** |
| Dynamic Home cards (Today, growth chips, recommendations) | `db.py` | Restructure/add to, not rebuild. |
| No weekly/scheduled anything | — | Needs a mechanism (§8). |
| No location or friend-graph data | — | Out of scope (§7, §18). |

---

## 4. Journey vs. Speaker Progression — Option C, adopted

Both your v1 draft and your review agree on this, so it's promoted from "open decision" to **adopted default** — flag in §18 only if you actually want to override it.

- **Journey** — unchanged. The 7-level, 35-lesson, World-named curriculum. A structured "how to learn" path.
- **Speaker Rank** (new) — a separate, always-visible progression driven by cross-mode Speaker XP: **Starter → Speaker → Confident Speaker → Fluent Communicator → English Pro.** Named "Rank," not "Level," specifically to avoid colliding with "Journey Level 3."
- Phase 1 ships Speaker Rank on **XP thresholds** (fast to ship). The schema (§6) is built so **milestone-gating** (e.g. "Starter→Speaker needs 500 min spoken AND 20 conversations AND 1 Confidence Check," not just an XP number) can be added later without a schema change — the checklist criteria read from the same `SessionScore`/`WeeklyStat` rows a threshold check would use anyway.

### Exact thresholds — locked

Not left as "some XP number," since a rank system with unstated numbers is unshippable. Calibrated against §2.1's formula (a 10-minute Face-to-Face session ≈ 115 XP, so these translate to a rough pace, not just abstract numbers):

| Rank | Speaker XP required | Rough pace at moderate use (~150 XP/day) |
|---|---|---|
| Starter | 0 (default) | Day 1 |
| Speaker | 750 | ~1 week |
| Confident Speaker | 2,000 | ~2-3 weeks |
| Fluent Communicator | 4,500 | ~1 month |
| English Pro | 9,000 | ~2 months |

Deliberately front-loaded (Speaker and Confident Speaker come fast, so the rank system proves itself in the first week) and back-loaded at the top (English Pro takes sustained months, so it still means something by the time a 6-month season closes around it).

### Streak — what counts as a qualifying day, locked

A day only counts toward `streak_days` if it has at least one session meeting **both**: (a) `effort_multiplier = 1.0` from the §2.1/§13 genuine-effort check, **and** (b) a hard floor of **≥3 minutes spoken OR ≥5 user turns** (whichever the mode measures) — reusing the exact same gate XP already uses, not a second concept. This closes the "open the app, say one sentence, streak maintained" gap directly: a token session fails the floor, doesn't count, and (per §2.1) wouldn't have earned meaningful XP either.

---

## 5. The four modes — each with a distinct purpose

| Mode | Purpose | Feeds Speaker Progression via |
|---|---|---|
| 🗣️ **Daily Talk** | Comfortable practice — speak Hindi, be understood, hear it back in English, no pressure to perform in English yet | Minutes, thought-complexity, and a **unique metric**: count of thoughts expressed that DuSu translated to English (see below) |
| 🎤 **Interview** | Structured pressure — think and answer under interview conditions | Full existing `SCORER_SYSTEM` rubric (kept as-is) + Speaker XP |
| 👥 **Face-to-Face** | The confidence arena — real, unscripted English conversation | New per-mode Performance score (confidence/continuity/vocabulary/depth) + Speaker XP |
| 🗺️ **Journey** | Systematic learning — the curriculum | Lesson XP (existing, unchanged) also contributes to Speaker XP |

**Daily Talk's unique metric** (new, from your review): Daily Talk already produces an `english` field every turn — the clean English translation of what the user just said in Hindi/Hinglish (`DAILY_TURN_SYSTEM`, already built). That field is currently used once and discarded. Counting and storing it turns "how many thoughts did I express that got shown to me in English today" into a genuinely unique, ownable DuSu metric — no other mode/product has this shape, because no other mode has Daily Talk's Hindi-first-then-English-reflection mechanic. Cheap to add (the data already exists in every daily turn response) and worth its own line on the post-session screen: *"You expressed 17 thoughts in English today that you said in Hindi."*

**Locked: counted deterministically, never LLM-reported.** `thoughts_translated` increments by exactly 1 in application code for every Daily Talk turn where `daily_turn()`'s response has a non-empty `english` field — not asked of (and never trusted from) the end-of-session summary call. A summarization model recalling "roughly 17" is a plausible-sounding guess; counting real turns as they happen is a fact.

---

## 6. Database schema — concrete, for speed

Design principles carried over from this session's earlier work: reuse `Memory.facts` (schemaless JSONB) for per-user, non-cross-queried data; use a real indexed table wherever a query needs to rank/aggregate **across users** or **across time**, because that's exactly where JSONB scanning gets slow. Every new table below follows this repo's existing pattern (`Mapped[...]`, `mapped_column`, `create_all` for new tables — no migration risk; any new **column** on an *existing* table needs the `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` treatment `init_db()` already uses for `status`/`mode`).

```python
# --- New columns on existing Progress table (needs ALTER TABLE IF NOT EXISTS in init_db) ---
# Progress.speaker_xp:   Integer, default=0, indexed        # participation currency (§2)
# Progress.speaker_rank: String(24), default="starter"      # cached current rank, avoids recomputing on every read

# --- New table: one row per finished session, the core fact table everything else derives from ---
class SessionScore(Base):
    __tablename__ = "session_scores"
    id:          Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id:     Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    mode:        Mapped[str] = mapped_column(String(32))            # daily | conversation | interview
    created_at:  Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    minutes:     Mapped[float] = mapped_column(default=0.0)
    xp_earned:   Mapped[int] = mapped_column(Integer, default=0)
    confidence:  Mapped[int] = mapped_column(Integer, default=0)    # 0-100, Performance components
    continuity:  Mapped[int] = mapped_column(Integer, default=0)
    vocabulary:  Mapped[int] = mapped_column(Integer, default=0)
    grammar_trend: Mapped[int] = mapped_column(Integer, default=0)
    depth:       Mapped[int] = mapped_column(Integer, default=0)
    overall:     Mapped[int] = mapped_column(Integer, default=0)
    thoughts_translated: Mapped[int] = mapped_column(Integer, default=0)  # Daily Talk's unique metric, 0 for other modes
    genuine_effort: Mapped[bool] = mapped_column(Boolean, default=True, index=True)  # from SESSION_MEMORY_SYSTEM (§20) — drives XP multiplier, streak, "meaningful minutes", and Performance-trend inclusion (§2.2)
    # Composite index (user_id, created_at DESC) for "recent sessions" / trend queries (Before-vs-Now, Confidence Check deltas).
    # Composite index (user_id, mode, created_at DESC) for per-mode history without scanning other modes' rows.

# --- New table: the weekly rollup a League query actually reads (never scan SessionScore live for a leaderboard) ---
class WeeklyStat(Base):
    __tablename__ = "weekly_stats"
    user_id:        Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    week_start:      Mapped[dt.date] = mapped_column(Date, primary_key=True)   # composite PK: one row per user per week
    minutes_spoken:  Mapped[float] = mapped_column(default=0.0)
    sessions:        Mapped[int] = mapped_column(Integer, default=0)
    xp_earned:       Mapped[int] = mapped_column(Integer, default=0, index=True)
    avg_score:       Mapped[int] = mapped_column(Integer, default=0)
    journey_level:   Mapped[int] = mapped_column(Integer, default=1)   # DENORMALIZED snapshot of Profile.level at write time —
                                                                        # avoids a join on every "League, by your level" read.
    xp_reached_at:   Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)  # bumped every time xp_earned
                                                                        # increases this week — the tie-break field below reads this directly
    # Index (week_start, xp_earned DESC)                 -> fast global weekly Top-N
    # Index (week_start, journey_level, xp_earned DESC)   -> fast by-level weekly Top-N, no join

# --- New table: cross-user season award computation needs indexed rows, not per-user JSONB blobs ---
class SeasonAward(Base):
    __tablename__ = "season_awards"
    user_id:     Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    season_id:   Mapped[str] = mapped_column(String(16), primary_key=True)   # e.g. "2027-H1"
    award_key:   Mapped[str] = mapped_column(String(48))                    # e.g. "most_consistent", "biggest_improvement"
    computed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    stats:       Mapped[dict] = mapped_column(JSONB, default=dict)          # the snapshot backing the award (for the share card)
    # Index (season_id) -> the batch "compute every award for this season" query at season close.
```

Kept as schemaless `Memory.facts` (no change needed, no cross-user queries against these):
- `weekly_missions`: `{week_start, missions:[{id, text, target, progress, xp}]}`
- Achievement/badge data — stays on `Progress.badges` (small list, always read whole, no query pattern needs indexing).

**Why this split (the "perfect schema" ask, explained):**
1. **`SessionScore` is the fact table.** Every derived thing — Before-vs-Now charts, Confidence Check deltas, "your trend this month" — reads from here with a plain indexed date-range query. Without it, that data only exists buried in `Memory.facts["daily_stats"]`/`Conversation.summary` text, which can't be aggregated or ranged efficiently.
2. **`WeeklyStat` is a rollup, not a live aggregation.** A leaderboard query must never compute "sum this week's XP for every user" live at read time — that's an O(all users × all sessions) scan under any real load. Writing one small row per user per week (updated incrementally at session-end, not recomputed) makes the leaderboard read O(log n) via the index, regardless of how much history exists.
3. **Denormalizing `journey_level` onto `WeeklyStat`** trades a tiny bit of write-time duplication for avoiding a join on every single leaderboard read — leaderboard reads happen far more often than level changes, so this is the right side to optimize.
4. **`SeasonAward` exists because season-close is a genuine batch job** ("for every user, find their leading stat, assign a title") — that needs to scan indexed rows by `season_id`, which a per-user `Memory.facts["seasons"]` blob can't do without loading every user's memory document one at a time.

### `mode` enum — checked against real code, not changed

A review pass suggested renaming the `mode` values to match the product-facing name "Face-to-Face." **Checked against the actual WebSocket protocol and declined**: `engine.py`'s `MODES = ("interview", "conversation", "learning", "daily")` is the real, already-live wire value — it's what the client sends in the `start` frame's `mode` field today, in production. Renaming `SessionScore.mode` to `face_to_face` would create a second, different vocabulary for the same concept (client says `conversation`, this new table would say `face_to_face`) — worse, not better, consistency. **Locked: `SessionScore.mode` uses the exact same strings already flowing through the app** (`daily`, `conversation`, `interview`) — "Face-to-Face" stays a display label only, same relationship "Journey" already has to its own internal representation.

### Weekly League tie-break — locked

Two users can land on identical XP. Deterministic order, so a leaderboard never renders differently on refresh: **`xp_earned` DESC → `minutes_spoken` DESC → `sessions` DESC → `xp_reached_at` ASC** (whoever reached that XP total first wins the tie). `xp_reached_at` is a real column on `WeeklyStat` (above) — bumped every time `xp_earned` increases that week, not derived after the fact.

---

## 7. Feature spec, phased (revised per your review)

### 🚀 Phase 1 — "Make Speaking Count"

1. Speaking Score across all modes (piggyback on the existing end-of-session `SESSION_MEMORY_SYSTEM` call — one extra JSON field, not a second LLM call).
2. Speaker XP for all speaking activities, not just lessons/Daily (fixes the biggest current gap — §3).
3. Post-session results screen for Daily Talk + Face-to-Face (Interview already has one) — reuses the existing report screen's visual language, **exact content order locked**: session duration → XP earned → Speaking Score delta (headline `overall` number only — the 5 components are tap-to-expand, not shown by default, per §12's anti-casino/no-overwhelm rule) → **Daily Talk only: "thoughts translated" headline line, right after the Speaking Score delta and before streak** (this row simply doesn't exist on the Face-to-Face/Interview versions of the same screen) → streak status → rank/league movement → next target. Not a wall of every metric at once.
4. Weekly Speaker League — global + by-Journey-level, backed by `WeeklyStat` (§6). Every row uses §15's "next target" copy pattern (e.g. "#17 — 12 XP to #16"), not a bare rank number.
5. Speaker Rank on Home (XP-threshold version, exact numbers locked — see §4).
6. Dynamic Home redesign — answers, in order: *Who am I becoming? How am I doing? What did I do? Where do I stand? What next?* (see §7a below).
7. **Basic** Before-vs-Now (promoted from Phase 2 per your review) — **even cheaper than v2 stated**: a working version already exists (`renderBecoming()`, "Who you're becoming," Day-1 vs. Today text + longest-conversation stat). Phase 1 extends this existing card with the new Speaking Score deltas, rather than building a screen from scratch.
8. **Basic** Confidence Check (promoted from Phase 2 per your review — a single 30-day, 2-minute structured check, reusing the existing assessment voice-capture flow).

### 🔥 Phase 2 — "Make Users Chase Progress"

9. Personalized Weekly Missions (rules-based on stored stats, not LLM-based — cheap, instant).
10. Achievement Gallery screen (extends existing badges).
11. Named/tiered Speaking Streaks (3/7/30/100/180 days — reuses existing `streak_days` verbatim, just new copy + badges).
12. Deeper Confidence Check (fuller comparison history, not just latest-vs-previous).
13. Deeper Before-vs-Now (richer timeline, not just two snapshots).
14. Rank milestone-gating (checklist criteria replacing pure XP thresholds — schema already supports this per §4/§6, this phase just writes the criteria logic).
15. Interview adaptive difficulty — scale question difficulty using data already available (Journey level, past interview `SessionScore`/`SCORER_SYSTEM` history, stated career goal from the Career Roadmap goal field) so a candidate's 5th interview isn't the same difficulty as their 1st. No new data collection required, purely a prompt enhancement to `interviewer_system()` — held to Phase 2 rather than folded into Phase 1 to keep §7b's frozen boundary honest (Phase 1 doesn't touch the interview prompt at all beyond what's already shipped).

### 🏆 Phase 3 — "Make DUSU a Long-Term Identity"

16. 6-Month Speaker Awards (`SeasonAward`, different titles per user based on leading stat).
17. Shareable achievement/award cards.
18. Seasonal recognition surfaces (Home banner, etc.).
19. Advanced leaderboard segmentation (friends, country/city) — **only if retention data from Phases 1-2 justifies the extra infrastructure.** Both remain explicitly out of scope until then (§18).

### 7a. Home screen — the five questions

Per your review, redesign Home's priority ordering to answer, top to bottom, before the mode buttons even appear:

1. **Who am I becoming?** → Speaker Rank (e.g. "Confident Speaker")
2. **How am I doing?** → headline Performance delta (e.g. "Confidence 72 ↑8%")
3. **What did I do?** → this week's activity (e.g. "1h 42m this week")
4. **Where do I stand?** → League position (e.g. "#17 this week")
5. **What should I do next?** → the single nearest target (e.g. "12 minutes → challenge #16")

Then the four mode buttons underneath, unchanged in position. This is a restructure of the existing dynamic Home cards (`build_today`/`build_growth`/`build_recommendations` already provide pieces of this), not a rebuild.

### 7b. Phase 1 — the frozen implementation boundary

Exactly the 8 items above and nowhere else. Locking this explicitly because the fastest way to blow a "Phase 1" is to let it quietly absorb Phase 2/3 items mid-build:

**In Phase 1**: Speaking Score (all modes) · Speaker XP (all modes) · post-session results (Daily + Face-to-Face) · Weekly League (global + by-level) · Speaker Rank on Home (XP-threshold) · Dynamic Home redesign · basic Before-vs-Now (extending `renderBecoming()`) · basic Confidence Check.

**Not in Phase 1, no matter how easy it looks mid-build**: Weekly Missions, Achievement Gallery, named streak tiers, deeper Confidence Check/Before-vs-Now, rank milestone-gating, 6-month awards, shareable cards, friends/country leaderboards. All of §7's Phase 2/3 list, unchanged.

The loop Phase 1 alone must prove, end to end, before anything else gets built: **TALK → MEASURE → EARN XP → SEE PROGRESS → SEE RANK → SEE NEXT TARGET → COME BACK.** If that loop doesn't hold up under real usage, no amount of Phase 2/3 feature work fixes it — that's the actual reason to hold the line here rather than build broad.

### 7c. Mandatory pre-ship verification (not optional, not "test later")

Before Phase 1 is called done, the extended `SESSION_MEMORY_SYSTEM` call must be verified the same way the Career Roadmap feature and the Conversation Engine fix already were earlier this session — against real models, not by reading the prompt and assuming it works:

1. **Real session → real prompt → real JSON** — run an actual Daily/Face-to-Face/Interview session through the extended scoring call and confirm the response parses, contains all 5 components in range, and the `overall` weighted average computes correctly.
2. **Token budget check** — confirm the bigger JSON payload (session summary + facts/events extraction + 5 new score fields + `genuine_effort` + `recent_questions`, all in one call) doesn't hit the truncation failure this exact codebase already has a documented precedent for (`daily_turn`'s 700→1100 fix). Verify with a real call, adjust `max_tokens` from evidence, not a guess.
3. **Latency check** — confirm the heavier single call doesn't push session-end processing (`_persist_session()`) into noticeably slower feels — this call already runs at every session end today, so it's a delta to measure, not a cold start.
4. **Score plausibility check** — run a handful of deliberately-varied test sessions (strong effort, one-word-answers, mid-conversation give-up) and confirm the components move in the expected direction for each — this is what catches "the model just returns 70 for everything" before real users see it, not after.

Same discipline as the career-roadmap and conversation-engine work already done this session — this section exists so that standard doesn't quietly drop for the next feature.

---

## 8. Infrastructure gap: "weekly" needs a clock

Unchanged from v1 — Render's free tier has no cron. **Recommendation: lazy on-read rollover** (compute the week-boundary transition whenever a request notices `week_start` has passed, no scheduled job). See v1 rationale; still holds.

### Week boundary timezone — locked, and deliberately not per-user

A review pass suggested storing each user's timezone so week boundaries land correctly for them individually. **Checked against existing code and declined in favor of something simpler**: this exact codebase already has a precedent for exactly this problem — `_quota_day()` (the free-tier daily-request-limit reset) already uses a **fixed server-side IST day**, explicitly ignoring whatever day the client claims. DuSu's stated user base is India-first. Given that precedent and that audience, adding per-user timezone storage (a new field, new onboarding question, new privacy-policy line) to solve a problem the app already has a working, simpler answer to would be new complexity in service of an edge case (non-India users landing on a slightly-off week boundary) that doesn't currently matter to the product. **Locked: `week_start` uses a fixed IST week (Monday 00:00 IST), matching the existing `_quota_day()` pattern exactly** — same function, different period length, no new data collection.

---

## 9. Performance & latency plan (new — "make the system fast")

Two separate problems: **database access speed** (solved by §6's schema) and **AI-model round-trip speed** (the "connecting to AI model took time" issue you flagged, and which this session already hit twice — the 65-second career-roadmap generation and the earlier daily-turn truncation bug).

### Why AI calls feel slow today (root causes, not guesses)

- The provider chain (`_complete()`) tries providers **sequentially** — gemini, then groq, then openrouter, then github — only advancing on failure or cooldown. If the first-choice provider is just *slow* (not failing), the user waits for it regardless of whether a faster provider would've answered already.
- **Gemini is tried first** for every call type today, including fast conversational turns. Groq is generally the fastest inference provider available in this stack (LPU-based, near-instant token generation) — it's currently second in line.
- Large one-shot generations (career roadmap, full assessments) request big `max_tokens` budgets, and generation time scales with output length on most providers — this is inherent to those specific calls, not fixable by infrastructure alone.
- The WS `start` handler currently awaits several memory-loading DB calls **sequentially** (`get_memory`, `recent_summaries`, `relationship_stage`) before a session can even begin.

### Concrete levers, ranked by effort vs. payoff

| Lever | Effort | Payoff | Recommendation |
|---|---|---|---|
| **Reorder the chain per call-type**: try Groq first for latency-sensitive per-turn calls (conversation/interview/daily turns); keep the existing gemini-first order for one-shot heavy generations (roadmap/assessment) where quality-per-call matters more than speed | Low (config change) | High for perceived chat responsiveness | **Do in Phase 1** |
| **Parallelize the session-start memory loads** (`get_memory` + `recent_summaries` + `relationship_stage` via `asyncio.gather` instead of sequential awaits) | Low | Shaves fixed latency off every session start | **Do in Phase 1** |
| **`SessionScore`/`WeeklyStat` indexed schema** (§6) | Medium (already the schema plan) | Removes DB-side latency from leaderboard/history reads entirely | Ships with §6 |
| **Hedge/race two providers** for the single next conversational turn (fire both, take whichever answers first, cancel the loser) | Medium | Cuts tail latency when the "first choice" provider is having a slow day | Consider for Phase 2 if Groq-first alone isn't enough — costs an extra API call on every hedge, so only worth it if latency is still a complaint after the cheap fixes above |
| **Streaming responses** (start TTS on partial sentences instead of waiting for the full completion) | High (real architecture change — WS protocol, TTS pipeline) | Highest ceiling — this is what actually makes a reply feel instant regardless of total generation time | Flag as the long-term fix, not this round — bigger than this plan's scope |
| **"Still thinking…" reassurance after N seconds** | Trivial (client-only) | Doesn't reduce latency, but reduces the *feeling* of a stuck app during genuinely slow free-tier calls | Cheap enough to just do alongside Phase 1 |
| Connection pooling / keep-alive to providers | None needed | — | **Already correct** — `AsyncOpenAI` clients are already cached per provider, no change needed |
| Render cold start (30-50s after 15 min idle) | N/A (platform limit) | — | Unrelated to AI latency specifically; a keep-alive ping helps but Render's free tier may still cycle regardless — don't over-promise this one |

**Bottom line for Phase 1**: reordering providers for chat calls + parallelizing session-start DB loads are both cheap, safe, and address the actual observed slowness without a bigger architecture change. Streaming is the real long-term answer but is its own project.

---

## 10. Color theme reference (new — for final development)

DuSu's actual current tokens (verified in `test_client.html`, not guessed) — **reuse these for every new screen in this plan**, don't invent a parallel palette:

```css
--bg0:#070a14; --bg1:#0b1020; --bg2:#0e1428;      /* navy background gradient */
--ink:#f3ecd8; --ink-dim:#c8bd9e; --ink-faint:#8a815f;   /* warm parchment text, 3 weights */
--gold:#6f8cff; --gold-lt:#9db4ff; --gold-dk:#4257c9; --champ:#c9d4ff;  /* the "gold" accent is actually periwinkle-blue */
--green:#4fd6a0; --amber:#f0a952; --rose:#e08a7a;  /* existing semantic colors — currently under-used */
--grad: linear-gradient(135deg,#9db4ff 0%,#6f8cff 50%,#7a5cf0 100%);   /* the premium "escalation" gradient */
--font-d: "Cormorant Garamond", Georgia, serif;    /* headings */
--font-b: "Inter", system-ui, sans-serif;          /* body */
```

### Proposed semantic mapping for this plan's new UI (your call to confirm/adjust in review)

| Element | Color | Why |
|---|---|---|
| **Speaker Rank escalation** — each rank should visibly look "more premium" than the last | Starter: `--ink-faint` outline · Speaker: `--champ` · Confident Speaker: `--gold-lt` · Fluent Communicator: `--gold` · English Pro: full `--grad` badge | Reuses the existing 4-stop intensity scale already in the palette instead of inventing new colors — the visual escalation *is* the reward, culminating in the same gradient already used for premium buttons/highlights elsewhere in the app. |
| **Performance deltas** (Confidence/Before-vs-Now, up or down) | Improvement: `--green` · Decline: `--rose` | These already exist as semantic tokens and are barely used today — this is their natural home. |
| **League position change** | Rank up: `--green` arrow · Rank down: `--rose` arrow · Unchanged: `--ink-faint` | Same existing tokens, consistent with Performance deltas above. |
| **XP / participation** | `--amber` | Currently unused for anything gamification-related — free to claim as "XP's color" without colliding with anything else, and amber reads as "currency/reward" without competing visually with the rank-escalation blue/gold scale. |
| **Streak fire** | `--amber` → `--rose` gradient for higher tiers (3/7 day = `--amber`, 30/100/180 = warmer toward `--rose`) | Keeps the existing "fire = amber" association from other apps while still only using tokens already in the palette. |
| **Mission progress bars** | `--grad` (same as existing `.gt-bar`/`.cc-bar` fills) | Consistency — every progress bar in the app already uses this gradient; new ones should match, not introduce a second progress-bar style. |
| **Confidence Check "before" vs "now" panels** | Before: `--ink-faint` / dimmed card · Now: full-color `--ink` / `--grad`-accented card | Visually reinforces "then vs. now" without needing new colors — dim-to-vivid is itself the metaphor. |

No new CSS variables are proposed — everything above is a **mapping of existing tokens to new meanings**, which keeps the whole app visually coherent and means implementation never needs a "which blue is this" decision.

---

## 11. Conversation Engine — already shipped, not a gap

The review's §3 ("Interview must be continuous... this needs a Conversation Engine section, not just scoring") describes exactly the dead-end/repetition bug that was **found, root-caused, fixed, and shipped earlier in this session** — before this progression plan existed. Restating here so the master plan doesn't imply outstanding work:

- `conversation_system()` and `interviewer_system()` were rewritten with explicit anti-dead-end rules (banned generic replies, escalating question depth, no repeated questions, real follow-up on what the user actually said).
- Cross-session "don't repeat these questions" memory now exists (`recent_questions`, extending the existing end-of-session summary call).
- A short-reply retry guard now runs on all three talking modes.
- Interview's bounded completion (`INTERVIEW_COMPLETE:` → scored report) was **deliberately kept**, not made unending — that marker is what makes the scored report possible at all, and removing it would break the feature, not improve it. "Continuous" there means *continuously follows up before it ends*, not *never ends* — confirmed as the right reading during that fix.
- Live-tested against real models, not just prompt text — see `PLAYSTORE_LAUNCH_PLAN.md` §6 for the full root-cause writeup and verification transcripts.

**Nothing new to build here.** If repetition or shallowness resurfaces after Phase 1 ships (e.g. once real usage volume exists), the next lever is the fuller "Conversation Context Package" architecture that fix's writeup already scoped as a deferred option — not a new investigation.

### The hard rule, stated once, and where it already lives in code

> A conversation must not naturally terminate after a generic greeting or a single response. Every reply either follows up meaningfully or (Interview only) ends via `INTERVIEW_COMPLETE:`.

```
User speaks
 ↓
DuSu understands context           →  facts_summary + session transcript, already passed every turn
 ↓
DuSu responds                      →  reacts to what was actually said (banned dead-end list, prompts.py)
 ↓
DuSu references prior conversation →  facts_summary's "recent chats"/"where you left off" + recent_questions
 ↓
DuSu goes deeper, not sideways      →  escalating depth rule (fact → reason → experience → reflection → future)
 ↓
DuSu asks ONE meaningful question   →  never repeats (recent_questions, in-session transcript scan)
 ↓
[length/quality floor]              →  short-reply retry guard (engine.py), one retry before accepting
 ↓
User responds → repeat
```

Every arrow above is already implemented, not proposed — this is the frozen spec restated as a diagram specifically so a future contributor (or future you) can check any single arrow against the actual prompt/engine code and confirm it's still true, rather than re-deriving the rule from scratch.

### The checklist form of the same rule (for Conversation and Face-to-Face specifically)

Every DuSu turn should be doing at least one of these — this is the operational form of "goes deeper, not sideways" above, not a new requirement:

1. Continue the current topic.
2. Reference something the user previously said (this session or, via `facts_summary`, a prior one).
3. Introduce a relevant new topic once the current one is genuinely exhausted.
4. Ask a meaningful, specific follow-up.
5. Gently challenge or probe an opinion the user gave.
6. Ask for a concrete example.
7. Ask why / how / what happened next / what changed.
8. Connect to a known interest (`facts_summary`'s interests/dream/profession).
9. Escalate depth (fact → reason → experience → reflection → future) rather than resetting to a fresh surface-level question.

And the closing rule, unchanged from what's already shipped: **every response in an active conversation ends with a meaningful question or conversational invitation, unless the user explicitly asked to stop.**

### Interview — the same shape, bounded

`interviewer_system()` already runs: **question → answer → follow-up → deeper follow-up → next competency**, not `Q1 → A1 → Q2 → A2 → end` — the fix earlier this session specifically added "two or three connected follow-ups on one good answer beats jumping to the next scripted topic" and banned bare acknowledgement-only turns. What's **not** yet built (locked as Phase 2 item 15, §7): scaling question *difficulty* itself using the candidate's history, not just following up on the current answer — that's additive to what already exists, not a fix to something broken.

### Daily Talk — purpose sharpened

Refining §5's framing to be more precise: Daily Talk's job isn't "translate Hindi" — it's **helping the user express increasingly complex thoughts while keeping the conversation comfortable and alive**, in Hindi first, with the English reflection as a byproduct they get to hear, not the point of the exchange. `DAILY_TURN_SYSTEM` already reflects this (the 6-step reply shape, escalating emotional depth, forbidden generic phrases) — this is a framing clarification for how the team talks about the mode, not a prompt change.

---

## 12. Design System

### Typography & base palette — already fixed, reuse as-is

Already defined and used consistently: `Cormorant Garamond` (headings) + `Inter` (body), the navy background gradient, and the token set in §10. Nothing new needed here — just don't introduce a second font or a second background treatment for new screens.

### Dark-only, and that's a decision, not an oversight

DuSu has **no light theme anywhere in the current code** — one fixed dark-navy palette. Given `BRAND-UI-PLAN.md`'s positioning ("premium navy + gold" identity) is already a deliberate brand choice, not a placeholder:

**LOCKED: dark-only, permanently.** A calm, premium, "confidence coach at night" feel is part of the actual brand identity already established — adding a light mode would be real design + engineering work (every token, every gradient, every contrast ratio re-derived) in service of a requirement nobody has actually asked for.

### Mode accent colors — three already exist, two need assigning

Already shipped (`test_client.html`, `.mode-card` accents): **Learn** `#7c86c9` (soft indigo) · **Face-to-Face Talk** `#56b39a` (teal-green) · **Interview** `#cf9a8f` (dusty coral). These are used sparingly (a card border/icon tint), never a full re-skin — the base DuSu navy/gold language stays dominant everywhere, exactly the balance the review asked for ("every mode its own identity, but the whole app must still feel like DUSU").

**LOCKED, the two that weren't yet assigned**: **Daily Talk** → `--green` (`#4fd6a0` — already a semantic token, reads as "warm/growth," fits Daily Talk's low-pressure positioning) · **Journey** → `--gold`/`--champ` (the curriculum is DuSu's most "premium path" framing already, matches its own existing World-narrative visual treatment).

### Design System v1 — locked checklist

Every item the review asked to see locked, in one place:

| Item | Locked value |
|---|---|
| Primary | `--gold` / `--grad` |
| Secondary | `--champ` |
| Background | `--bg0/1/2` navy gradient (existing) |
| Surface / card | `--glass` fill + `--glass-brd` border (existing `.card`) |
| Text (3 weights) | `--ink` / `--ink-dim` / `--ink-faint` (existing) |
| Success | `--green` |
| Warning | `--amber` |
| Error | `--rose` |
| XP / reward color | `--amber` |
| Rank colors | Starter `--ink-faint` outline → Speaker `--champ` → Confident Speaker `--gold-lt` → Fluent Communicator `--gold` → English Pro full `--grad` |
| Journey identity | `--gold` / `--champ` |
| Daily Talk identity | `--green` |
| Interview identity | `#cf9a8f` (existing) |
| Face-to-Face identity | `#56b39a` (existing) |
| *(Learn/Translate — existing 5th mode, unaffected)* | `#7c86c9` (existing, untouched) |
| Dark/light theme | Dark-only, permanent |
| Typography | `Cormorant Garamond` (headings) + `Inter` (body) |
| Button/card style | Existing `.btn` / `.card` / `.mode-card` conventions only — no new button style |
| Progress bars | `--grad` fill on `rgba(255,255,255,.08)` track (existing `.gt-bar`/`.cc-bar` pattern) |
| Badges | Existing `BADGE_LABELS` emoji+text chip style, extended not replaced |
| Animations | `prefers-reduced-motion` always respected; celebrations reserved for rank-up / achievement unlock / streak milestone only (anti-casino rule, below) |

Nothing in this table is a new invention — every row points at a token, class, or pattern that already exists in the app today. That's deliberate: it's what makes this "locked" rather than "a new design system to go build."

### Color meaning, locked (not decided per-screen)

Formalizing what's already mostly true in practice, so it doesn't drift as new screens get built:

| Meaning | Token | Already used for |
|---|---|---|
| Success / completed / improvement | `--green` | (currently under-used — see §10 mapping) |
| XP / reward / achievement | `--amber` | New, per §10 |
| Confidence / personal growth / premium progression | `--gold` / `--gold-lt` / `--grad` | Speaker Rank escalation, buttons, progress bars |
| Learning / knowledge / Journey | `--champ` (proposed) | New assignment above |
| Error / warning / decline | `--rose` | Delete-account button, League/Performance declines (§10) |
| Neutral / muted / not-yet-earned | `--ink-faint` | Locked achievements, Starter rank |

### Component & state vocabulary — reuse, don't reinvent

Already-established patterns new screens must match rather than duplicate:
- **Loading**: the `.spin` spinner (admin, keys verify) and the shimmer skeleton (`cc-skel`, built for the Career Roadmap card) — two loading idioms already exist; new screens pick whichever fits (spinner for "waiting on a request," shimmer for "content shape is known, values aren't yet").
- **Voice states**: the orb already has a defined vocabulary (`connecting` / `thinking` / `speaking` / `idle` / `error`) — any new voice-driven screen (Confidence Check) reuses this exact state machine, doesn't invent a new one.
- **Empty states**: the Career Roadmap's "What do you want to become?" empty-card pattern (icon-free, one line of copy, one CTA) is the template for "nothing here yet" everywhere (empty League row, no missions yet, no achievements yet).
- **Toasts/errors**: the existing top `#notifBar` pattern (auto-hide after 10s) is the one non-inline error/notice surface — new features surface errors through it, not a second toast system.

### Motion — already disciplined, keep the bar

`prefers-reduced-motion: reduce` is **already respected in at least 7 places** across the current CSS (mode cards, hero animations, journey banner, avatar/face animation). This is a real existing strength, not a gap — the rule for every new animated element in this plan (rank-up celebration, league-position-change arrow, streak-fire pulse) is simply: **it gets a `prefers-reduced-motion` fallback from the day it's built**, matching the standard already set, not a new standard to invent.

**Anti-casino rule (review's §10, formalized):** every animation/celebration must be tied to a real, infrequent event (rank-up, achievement unlock, streak milestone) — never a per-message or per-XP-tick animation. If a celebration would fire more than a few times a week for an active user, it's too frequent and should be toned down or merged into the post-session summary instead of popping up separately.

---

## 13. Trust, Safety & Data Truth

### Anti-gaming — extending a protection that already exists

This isn't a new category for DuSu — `_persist_session()` **already refuses to award anything for a 0-turn session** (`if session.turns <= 0: return`), specifically to prevent XP farming by opening and immediately closing sessions. Phase 1 extends this same principle rather than inventing a new anti-abuse system:

- **Minimum meaningful content, not just minimum turns.** A session with `turns > 0` but only one-word replies the whole way through shouldn't earn full Speaker XP. Cheapest implementation: the existing end-of-session `SESSION_MEMORY_SYSTEM` call already reads the whole transcript — add one more boolean field (`genuine_effort`) to that same JSON response, and scale XP by it. No new LLM call, same piggyback pattern as Speaking Score.
- **Cap XP per session** (a ceiling, not a per-message reward) so one very long idle-but-technically-active session can't dominate the Weekly League.
- **Don't let quantity alone move Performance scores** — this is already guaranteed by §2's XP/Performance split: Performance is a quality rubric, not a counter, so "gaming" it would require actually producing better speech, which is the whole point.

### AI-estimated vs. Measured — the "data truth" rule

Formalized per the review's §19, and it's a real credibility issue worth taking seriously: never let a user mistake a model's opinion for a hard count.

| Category | Examples | UI treatment |
|---|---|---|
| **Measured** (hard counts, no ambiguity) | Speaking minutes, session count, streak days, vocabulary word count, Journey lesson/test completion | Shown plainly, no qualifier needed |
| **AI-estimated** (a rubric judgment, not a measurement) | Confidence, continuity, grammar trend, conversation depth, all Speaking Score components | Shown with a small, consistent marker (e.g. a subtle "AI-estimated" label or icon on first appearance per screen) — not hidden, not alarmist, just honest |

This is a one-line UI convention, not a big feature — but it needs to be decided once (§18) and then applied everywhere Performance numbers appear, not left to be inconsistent screen-to-screen.

### Privacy — decision already tracked

Covered in §18 item 2 (unchanged from v2): keep the existing alias-based leaderboard privacy model as the default recommendation. Data collection/retention/deletion is already covered end-to-end in `PLAYSTORE_LAUNCH_PLAN.md` (privacy policy, self-serve account deletion) — not duplicated here.

---

## 14. Personal Best — cheaper than it looks

Partially **already shipped**: `renderBecoming()` (the existing "Who you're becoming" card, Day-1 vs. Today) already surfaces `longest_convo_sec` as a stat today. This is a real existing Personal Best data point already in production, not a new concept.

Phase 1 extends the same idea into its own small, explicit "Personal Best" block (on Home or the Achievement/Progress area — placement TBD at mockup stage):

- **Longest conversation** — already tracked (`longest_convo_sec`), just needs its own labeled card instead of living inside the Becoming section only.
- **Best confidence score** — needs `SessionScore` (§6) to exist first; trivial `MAX()` query once it does.
- **Best weekly speaking time** — needs `WeeklyStat` (§6); trivial `MAX()` query once it does.
- **Longest streak** — **locked, not "check at implementation time"**: add `Progress.longest_streak_days` (Integer, default 0 — new column, `ALTER TABLE IF NOT EXISTS` per §6's migration pattern). Updated whenever `streak_days` exceeds the stored value, on the same write that updates `streak_days` today. Without this, resetting a broken streak would silently erase the record it should be preserving.

This gives users who don't care about competing against strangers a competition against their own history instead — cheap to justify since most of the underlying data either already exists or falls out of schema this plan is already building.

---

## 15. "Next Target everywhere" — a global UX rule, not a feature

Formalizing the review's §14 as an explicit rule for every surface in this plan, not a one-off: **never show a number without also showing the nearest thing it unlocks.**

| Surface | Number alone (don't do this) | With a next target (do this) |
|---|---|---|
| Weekly League | "#17" | "#17 — 12 XP to #16" |
| Speaker Rank | "Speaker, 1,240 XP" | "Speaker — 260 XP to Confident Speaker" |
| Journey | "World 3" | "1 test away from World 4" |
| Streak | "6 days" | "1 more day → 7-Day Speaker" |
| Confidence Check | "Confidence: 72" | "6 points from your Personal Best (78)" |

This is a copy/data-shape rule to apply when building each of §7's Phase 1-2 features, not a separate deliverable — flagging it here so it's designed in from the start rather than retrofitted screen by screen later.

**Locked edge case: what shows when there's nowhere higher to go.** "0 XP to next rank" or a blank League row at #1 is a real gap in an otherwise-universal rule. Two fixed states, not left to improvise per screen: **League #1** → *"You're #1 — defend your position."* **Top Speaker Rank (English Pro)** → *"English Pro — keep building your Personal Best."* Both redirect the "next target" instinct toward defending a position or beating your own record (§14) instead of dead-ending the pattern.

---

## 16. Accessibility — mostly already solid, close the specific gaps

Grounded in what's actually already true, not a generic checklist:

**Already in place:**
- `prefers-reduced-motion` respected in 7+ places (§12).
- Voice failure already has a real fallback: `SR` (speech recognition) failures retry with backoff (`srFails` counter, `safeRestart()`), and a `#feed` text transcript already runs alongside every voice interaction — DuSu is voice-first but never voice-only today. New voice features (Confidence Check) must keep this same text-fallback pattern, not regress it.
- Status indicators already combine color + shape/emoji rather than color alone (e.g. admin's 🟢/🚫/⏳ status dots) — keep this convention for new status UI (League position arrows, rank badges: use an icon/arrow shape, not color alone, exactly like the existing precedent).

**Needs checking at implementation time, not designed from scratch:**
- Touch target sizing on any new small interactive elements (League row taps, mission checkboxes) — verify against a 44px-minimum baseline.
- Contrast ratios for the new semantic colors against the navy background, specifically `--green`/`--amber`/`--rose` at small text sizes (they're currently used sparingly; heavier use in League/Score UI means checking contrast properly, not just reusing the hex values from decorative contexts).
- Captions/transcript already exist for conversation; confirm the same applies to any new voice-driven screen (Confidence Check) before shipping it.

---

## 17. Document map — how the full product plan is actually covered

The review proposed a 10-part master architecture. Rather than merge two large planning documents into one (real risk of one of them silently going stale while the other gets updated), here's where each part actually lives:

| Review's proposed section | Where it lives |
|---|---|
| 1. Product Vision | §1 (this doc) |
| 2. Core Modes | §5 (this doc) |
| 3. Conversation Engine | §11 (this doc) — already shipped, cross-referenced to `PLAYSTORE_LAUNCH_PLAN.md` §6 |
| 4. Speaking Measurement | §2, §6 (this doc) |
| 5. Progression (Journey/Rank/XP/Personal Best) | §4, §6, §7, §14 (this doc) |
| 6. Motivation (Streak/Missions/League/Next Target/Achievements) | §7, §15 (this doc) |
| 7. Long-term Identity (Before-vs-Now/Confidence Check/Awards) | §7, §14 (this doc) |
| 8. Product Design (color/typography/theme/components/motion/accessibility) | §10, §12, §16 (this doc) |
| 9. Trust & Safety (privacy/anti-gaming/AI transparency) | §13 (this doc) |
| 10. Business (free/premium/Play Store/monetization) | **`PLAYSTORE_LAUNCH_PLAN.md`** — not duplicated here; that document already owns the growth-phase/BYOK/subscription strategy end to end |

Two documents, not one, because they answer genuinely different questions (this one: what should DuSu become; the other: how does DuSu legally and commercially ship) — but together they're the complete picture the review asked for.

---

## 18. Locked decisions (v1.0)

Every item from the last two review passes, closed out with a definitive answer rather than left open — that's what makes this v1.0 instead of another draft. Each used my own stated recommendation from earlier in this document, since nothing here got pushback across two rounds of review; any of these can still be reopened, but implementation proceeds on these defaults unless told otherwise.

1. **Journey vs. Speaker Progression** — **LOCKED: Option C** (§4), two parallel systems.
2. **Leaderboard identity** — **LOCKED: keep the existing alias-based privacy model.** No real names on the Weekly League for v1.0.
3. **Speaker Rank naming** — **LOCKED**: Starter → Speaker → Confident Speaker → Fluent Communicator → English Pro.
4. **Rank gating for Phase 1** — **LOCKED: XP-threshold** at launch; milestone-gating is a Phase 2 item (§7 item 14), schema already supports it without rework.
5. **Provider reorder for latency** — **LOCKED: Groq-first for per-turn chat calls** (conversation/interview/daily turns); Gemini-first stays for one-shot heavy generations (roadmap/assessment). Accepted tradeoff: possible small quality dip on chat turns in exchange for responsiveness — revisit if quality complaints outweigh the latency win in practice.
6. **Color mapping** — **LOCKED** as specified in §10/§12's Design System v1 checklist.
7. **Country/city and friends leaderboards** — **LOCKED: out of scope** through Phase 3. Revisit only if Phase 1-2 retention data (§19) justifies the added infrastructure.
8. **Weekly rollover mechanism** — **LOCKED: lazy on-read rollover** (§8) for v1.0.
9. **Daily Talk's "thoughts translated" metric** — **LOCKED: ships as a headline line on its post-session screen** from Phase 1 (§5, §7) — it's free (the data already exists every turn) and it's DuSu's most ownable, hardest-to-copy metric; no reason to hold it back to "later."
10. **Dark-only** — **LOCKED**, permanently (§12).
11. **Mode accent colors** — **LOCKED**: Daily Talk `--green`, Journey `--gold`/`--champ` (§12).
12. **AI-estimated labeling** — **LOCKED: yes, ship the Measured-vs-AI-estimated distinction** (§13) from Phase 1 — it's a one-line UI convention, not a feature, and it's the thing that keeps Confidence Check/Before-vs-Now credible rather than feeling like made-up numbers. Exact label wording/placement (text vs. icon vs. tooltip) decided at mockup stage, not here.
13. **Anti-gaming thresholds** — **LOCKED: the numbers in §2.1** (300 XP/session cap, 600 XP/day cap, 0.3× multiplier on low-effort sessions) ship with Phase 1 alongside the existing 0-turn guard — not deferred, since XP and the Weekly League both launch in Phase 1 together, and a league without any abuse ceiling on day one is the wrong order to ship things in.

---

## 19. Success metrics — how we'll know it worked

Requested explicitly, and it matters: without this, "did the retention system work" has no answer six weeks after launch.

**North star: weekly meaningful speaking minutes per active user** — "meaningful" = sessions that pass the `effort_multiplier = 1.0` gate from §2.1 (not just app-open time). Chosen over raw app opens or DAU because DuSu's actual job is getting people to speak, not to open the app — a metric that could go up while speaking time goes down would be measuring the wrong thing.

| Category | Tracked |
|---|---|
| **Conversation** | Sessions/user/week · average session duration · % of sessions >5 min · % of sessions >10 min · session-abandonment rate (started, near-zero turns) |
| **Retention** | Day 1 / Day 7 / Day 30 retention · weekly active speakers (distinct from weekly active *users* — must have at least one meaningful session) |
| **Progress** | Total speaking minutes trend · average Confidence delta trend · Journey completion rate · achievements earned per user |
| **Gamification** | Speaker XP earned/user/week · mission completion rate (Phase 2+) · League participation rate (% of active users who view the League at least once/week) · re-engagement proxy: % of sessions started within an hour of a post-session "next target" being shown |

All of these are queryable directly off the §6 schema (`SessionScore` for conversation/progress metrics, `WeeklyStat` for the gamification/League numbers) — no separate analytics system needed for v1.0.

---

## 20. SESSION_MEMORY_SYSTEM extension — the response contract (shape locked, wording is not)

A review pass correctly distinguished "the exact prompt sentence" (still fine to write at implementation time) from "the exact JSON shape and failure behavior" (should not be left to improvise). Locking the latter:

```
Extended response, in addition to the existing summary/facts/events/next_hook/recent_questions fields:
{
  "scores": {
    "confidence":    <int 0-100>,
    "continuity":    <int 0-100>,
    "vocabulary":    <int 0-100>,
    "grammar_trend": <int 0-100>,
    "depth":         <int 0-100>
  },
  "genuine_effort": <true|false>
}
```

Rules, locked:
- All 5 score fields and `genuine_effort` are **required** — this is an extension of an existing call that already has a defined failure mode (`summarize_and_extract()` returns `{}` on any exception), so a missing/malformed field is treated as a parse failure, not patched with a default.
- Values outside 0-100 are clamped, not rejected outright (consistent with how `LEVEL_TEST_SYSTEM`'s score parsing already handles messy model output elsewhere in this codebase).
- **On parse failure, stated precisely (a review pass correctly caught this being ambiguous)**: `genuine_effort` defaults to `false` for that session — which, via §2.1's existing formula, means the session still earns **0.3× XP** (participation is preserved; a broken model response shouldn't zero out a real session the user actually did). What it does **not** get: no `SessionScore` row's score components are treated as valid, and the session contributes to no Performance trend/delta/Before-vs-Now/Confidence-Check aggregate (§2.2's low-effort exclusion rule applies the same way it would to any other `genuine_effort=false` session — parse failure isn't a special case, it's just one more reason that flag can be false). The session's summary/facts/next_hook extraction (the part that already works today) is unaffected — only the new scoring fields degrade.
- `overall` is **not** requested from the model — it's computed in application code from the locked §2.2 weights, so the weighting can never silently drift based on how the model feels that day.

---

## 21. What this plan deliberately does NOT cover

- UI mockups for the new screens (League, Achievement Gallery, redesigned Home, post-session results) — next step now that §18 is locked, same pattern as the earlier Career Roadmap mockup.
- The exact prose/wording of the extended `SESSION_MEMORY_SYSTEM` prompt — the response *contract* is locked (§21), the sentence structure asking for it is copywriting, drafted at implementation time.
- Play Store / monetization interaction — lives entirely in `PLAYSTORE_LAUNCH_PLAN.md` (§17 document map), not duplicated here.
- Actually implementing anything in this document — locking the decisions is not the same action as writing the code; implementation is the next explicit step, not an automatic follow-on to this file being saved.

---

## 🔒 DUSU Speaker Progression — Product Spec v1.0.3 — IMPLEMENTATION BASELINE

Vision, four modes, conversation engine (shipped, plus the explicit checklist form), score-component definitions, XP formula with exact allocation semantics, exact Speaker Rank thresholds, streak-qualifying minimum and historical-max tracking, Weekly League with a real deterministic tie-break field, a fixed week boundary, locked post-session content order (including where Daily Talk's unique metric sits), "next target" edge cases at the top of every scale, missions, achievements, Confidence Check, Before-vs-Now (with low-effort sessions correctly excluded), 6-month awards, Home behavior, design system, privacy, anti-gaming (with `genuine_effort` persisted and its parse-failure behavior precisely stated), accessibility, a frozen Phase 1 boundary with a mandatory pre-ship verification gate, a locked response contract for the extended scoring call, and success metrics are all locked above. Six review passes, each finding real (shrinking) issues, none finding a reason to reopen product direction. **Backend/data-layer implementation starts from this document now** — UI mockups refine the frontend afterward, they don't gate starting.

# DuSu — Closed-Test Retry Plan (Google Play production access)

> Drafted 2026-10-06, the day the first production-access application came back **"Your app requires more testing"**.
> Companion docs: `PLAYSTORE_SUBMISSION_GUIDE.md` (store-form answers), `PLAYSTORE_LAUNCH_PLAN.md` (background).
> Every number below was measured on 2026-10-06 (production DB, live server, Google's help pages) unless marked *assumption*.

---

## 0. TL;DR

1. Google did **not** say "you are short of testers". It said testers weren't **engaged** and we didn't show we **gathered and acted on feedback through updates**.
2. Our own data agrees, and shows the cause is the **product funnel**, not the tester count: of 40 invited testers (excluding you), **25 never signed in, 4 ever held a session, 0 were active on more than one day**. At that conversion, 25 testers → ~2–3 engaged people.
3. So the plan is: **(a) fix the funnel first** (tester access without the 2-key wall, working server keys, a full-screen Play build, a fresh release), **(b) run a managed 14-day test** with ≥25 real testers, daily nudges, 3 releases and a visible "you said → we did" log, **(c) apply only when the Day-14 gate passes** (§8). A third rejection costs another 14+ days.
4. You need to make 6 decisions (§11), spend ~20 min/day, and do the Play Console steps only you can do (F4 copy the signing fingerprint, F5 upload each AAB, F6 baseline + feedback URL + Google Group).

---

## 1. What Google actually told us

**Our rejection (pasted 2026-10-06):** possible reasons — *testers were not engaged with the app during the closed test*; *testing best practices not followed, e.g. gathering and acting on user feedback through updates*. Next step: closed testing for **an additional 14 days with real testers**.

**Google's own rules** ([Play Console Help — testing requirements](https://support.google.com/googleplay/android-developer/answer/14151465), read 2026-10-06):
- **≥12 testers opted in continuously for ≥14 days.** A tester who opts in and leaves before 14 days does not count.
- The production-access form asks: how hard recruiting was; **whether testers used all available features and whether "tester usage matched expected production user behavior"**; a **summary of feedback and how it was collected**; **changes you made based on what you learned**; why you consider the app production-ready.
- After a rejection you may need to keep running the test if you have too few opted-in testers **or insufficient tester engagement**.

**Mechanics** ([closed-test setup help](https://support.google.com/googleplay/android-developer/answer/9845334)): testers join by opt-in link from an **email list or a Google Group**; up to 2,000 per list; a **feedback URL/email** you set is shown on the opt-in page; new releases reach opted-in testers **within minutes**.

**Community patterns — not Google statements, treat as hints** ([Testers Community](https://www.testerscommunity.com/blog/why-apps-fail-google-play-production-access), [Indie Hackers](https://www.indiehackers.com/post/google-play-production-access-rejected-why-fixes-1efcef20e8)): rejections cluster around testers who opted in but never launched the app, **no app updates during the window**, and vague form answers.

**Why "updates" matters for a TWA:** DuSu is a Trusted Web Activity — our web fixes deploy instantly but Google only sees a **new AAB release** on the closed track. The last AAB was built 2026-09-20 (v1.0 / versionCode 1). Web fixes alone will not look like "acting on feedback" to Google, so each web fix batch must ride a numbered release with real release notes (§10).

---

## 2. What our data shows (production DB, read-only, 2026-10-06)

41 emails in `playstore-testers.csv` (1 is yours → 40 non-owner testers).

| Funnel step (non-owner testers) | Count | Of previous step |
|---|---|---|
| Invited | 40 | — |
| **Ever signed in** | **15** | 37% |
| Got access (2 verified API keys) | 8 | 53% |
| **Ever completed a speaking session** | **4** | 50% |
| Active on ≥5 different days | **0** | — |
| Gave feedback in the app | **0** | — |

*(The funnel is not strictly nested: 2 of the 4 active testers never verified keys on the server — they got in through an earlier flow. The overall picture does not change.)*

- **Total tester usage outside the owner:** 16 sessions, ~10 minutes of speech. Best non-owner tester: 8 sessions, all on a single day. (You: 13 sessions on 6 days.)
- **Timeline:** sign-ups happened 09-21→09-23 (8 people), then **nothing for 9 days (09-24→10-02)**, then a burst on 10-03→10-05 (9 people). The middle of the window was empty — the opposite of "continuous engagement".
- **Feedback table: 1 item in total, submitted by the owner account.** No tester feedback, no Play-side feedback evidence.
- **Releases:** one build (1.0 / versionCode 1, built 2026-09-20). The wrapper source changed since (canonical domain, 2026-09-30) but no new AAB was shipped.
- Whole system: 17 users ever, 10 with verified keys, 6 with a session. Sessions by mode: Daily 24, Talk 3, Interview 3 (Learn mode is not recorded server-side by design).

**What the data cannot tell us:** people who opened the app but never completed Google sign-in are invisible to the DB (Play Console install/active-device stats fill that gap — read them on Day 0); and "never signed in" may include testers who never opted in at all. §6 finds out which, by phone.

**Funnel maths:** current conversion (40 → 4 sessions = 10%) means 25 opted-in testers produce ~2–3 engaged people; reaching 12 engaged would need ~120 invitations. **Recruiting more is the wrong lever; fixing the funnel is the right one.**

---

## 3. Root causes, ranked

| # | Cause | Evidence | Fix (where) |
|---|---|---|---|
| 1 | **Access wall:** every non-owner needs 2 verified third-party API keys (`access_phase = growth`, `MIN_VERIFIED_KEYS = 2`). Budget-Android students won't do that for a stranger's app. | 15 signed in → only 8 got access; 5 stuck before access | F1 |
| 2 | **Dead-ends after setup:** 6 testers have verified keys, onboarded, **never spoke once**. | 0 sessions, 0 xp, 0 conversations | F3, §6 (call 3 of them). *Hypotheses, not findings:* mic-permission prompt, non-Chrome default browser, Daily Talk stuck on "Thinking…" after a failed first turn (fixed 2026-10-04), key quota error, not knowing what to tap |
| 3 | **No human follow-up:** nobody chased the 25 who never signed in; silent middle of the window. | §2 timeline | §6, §9 |
| 4 | **No feedback loop:** no channel testers actually used, no visible changelog. | 1 feedback item (owner's) | F6, F8, §10 |
| 5 | **No updates shipped to the closed track.** | AAB from 09-20, source moved on | F5, §10 |
| 6 | **Server keys are failing** (measured today, one 8-token call per provider): Groq **401**, OpenRouter **404** (default model gone), GitHub **dead**, only Gemini works — and `/health` still reports all four "available" (it only tracks cooldowns). | probe 2026-10-06 | F2 |
| 7 | **Play-installed build won't be full-screen:** live `assetlinks.json` carries 1 fingerprint (upload key); the Play App Signing key is missing, so testers see a browser bar and the app looks like a web page. | `/.well-known/assetlinks.json` | F4 |

---

## 4. Success criteria

| Metric | Target | Measured by |
|---|---|---|
| Testers opted in (continuous) | **≥25** at Day 1; **≥12 for the full 14 days** (Google's bar) | Play Console → Closed testing → Testers |
| Distinct real people on Android phones | ≥20 (accounts you control may not be the majority) | roster (§6) |
| Testers active (≥1 session) in **each** window: D1–3, D4–7, D8–11, D12–14 | ≥70% of opted-in | SQL Q2/Q3 (App. B) |
| Testers active on ≥5 distinct days | **≥12** (aim 18) | SQL Q3 |
| Cohort sessions | ≥200 | SQL Q3 |
| Feature coverage (Daily, Talk, Interview, Learn) | ≥60% of testers used ≥3 modes; every mode used by ≥10 testers | SQL Q4 + survey (Learn isn't logged) |
| Feedback items | ≥40 from ≥15 testers; **100% acknowledged <24 h**; ≥80% resolved or answered <72 h | feedback sheet (App. C) |
| Releases to the closed track | **≥3**, each with notes tied to real feedback | Play Console → Releases |
| Device spread | ≥6 phone models, ≥3 Android versions | survey |
| Stability | crash-free users ≥99%, 0 ANRs | Play Console → Android vitals |
| First-turn success (a tester's first spoken turn gets an answer) | ≥95% | rehearsal + feedback (add counters: P1-2) |

---

## 5. Pre-flight — all must pass before Day 1

| ID | Task | Who | Effort | Done when |
|---|---|---|---|---|
| **F1** | **Decide tester access** (§11-D1). Recommended: tester-only server keys (Option B). | You decide; Dev builds | decision + ~2 h | A fresh tester account goes install → first spoken turn with **no key setup** |
| **F2** | **Fix server LLM keys** and make `/health` honest (live-probe, cached). New Groq key; a real Gemini `AIza…` API key (current `AQ.` token is OAuth-style and expires); refresh OpenRouter free models; drop dead GitHub provider. Required before F1 is safe. | You (keys); Dev (code) | ~1 h + ~1 h | 8-token probe passes on ≥2 providers; `/health` shows real status |
| **F3** | **Dress rehearsal on a clean phone** by someone who is *not* you: opt-in link → install from Play → sign in with a non-owner Google account → first Daily Talk turn → sign out → sign in again → resume. Time it. | You + 1 friend | 30 min | ≤3 min install→first answer; fix every blocker the same day |
| **F4** | **Add the Play App Signing SHA-256** to `ANDROID_CERT_SHA256` on the host. Play Console → Test and release → Setup → **App signing** → copy *App signing key certificate* SHA-256, send it to Dev. Verify live assetlinks lists 2 fingerprints. | You (copy); Dev (host) | 10 min | Play-installed app opens **full-screen** (no browser bar) |
| **F5** | **Release v1.1** to the closed track: `versionCode 2`, `versionName 1.1`, canonical host (already in source since 2026-09-30), + any native fix from F3. Notes: real changes only (§10). | Dev builds; You upload | ~1 h | Testers' Play page shows 1.1 |
| **F6** | **Play Console baseline + setup:** record today's opted-in count, installs, release history; set the **feedback URL/email** (Google Form or a monitored email); create a **Google Group** for testers and link it to the track; save a screenshot of the Dashboard "apply for production" counter. | You | 45 min | Baseline numbers written into the evidence log (App. C) |
| **F7** | **Roster ≥30 invited, ≥25 confirmed opted in** (§6). | You | 2–3 days | 25 people have replied "installed" with a screenshot |
| **F8** | **Comms kit ready:** WhatsApp group, Google Form (mid + final survey), feedback sheet, message templates (App. A). | You | 1 h | Group created; kickoff message sent |
| P1-1 | In-app **post-session feedback card** (👍/👎 + one line → existing `/feedback`). Raises feedback volume with zero tester effort. | Dev | ~2 h | Card appears after each session |
| P1-2 | **Funnel counters** (start / first-turn ok / error / quota / keys-required per day) so "first-turn success" is measured, not guessed. | Dev | ~2 h | Daily numbers in the report |
| P1-3 | **"Founding tester" badge** for testers with ≥5 active days (non-monetary thanks; uses existing badges). | Dev | ~1 h | Badge appears at Day 14 |

> **Status 2026-10-06 (evening) — F4/F5 progress.**
> - **Browser bar (X + URL) has two causes, one now fixed.** (1) The `DuSu-app.apk` at the repo root was **debug-signed** (public Android debug key, SHA-256 `75:1B:51…`), which can never match `assetlinks.json` — and our docs told people to ship the debug build. Replaced with the **release-signed** build; docs corrected (`INSTALLATION.md`, `README.md`, `android-twa/README.md`, `CLAUDE.md`). (2) **Play-installed builds** are re-signed by Google; that key isn't in `assetlinks.json` yet (still 1 fingerprint, the upload key) — **waiting for you to paste the Play App Signing SHA-256 (F4)**; the server already accepts a comma-separated list. Google's Digital Asset Links API confirms the web side is correct (`linked: true`) for the upload key on both hosts.
> - **F5 built:** `com.dusu.app` **v1.1 (versionCode 2)**, release-signed — APK + AAB verified against the key in `assetlinks.json`. AAB: `android-twa/app/build/outputs/bundle/release/app-release.aab` (you upload it to the closed track). Not yet verified on a phone.

---

## 6. Roster and recruitment

**Target:** 30 invited → ≥25 opted in at Day 1 (expect 20–30% drop-off). **Accounts you control must not be the majority** — Google asks for *real testers representing your audience*; DuSu's audience is freshers/students prepping for interviews and placements on budget Android.

**Status ladder** (the CSV `playstore-testers-status-2026-10-06.csv`, git-ignored, gives each tester's rung today):
`invited → opted in → installed → signed in → has access → first session → active ≥5 days`
Today: **25** invited-never-signed-in · **5** signed in but stuck before access · **6** have access but never spoke · **4** active · (1 owner).

**Phase 0 playbook (Days −4 → 0):**
1. **Phone/voice-note the 25 "never signed in" people first** (2 minutes each). Ask exactly one thing: *"Did you get the Play opt-in link and install it?"* This separates "never opted in" from "installed but couldn't sign in" from "used another Google account".
2. **Call 3 of the 6 "has access, never spoke"** testers and watch them (video call) tap through Start Speaking → mic permission → first turn. This finds the real dead-end (§3 #2). It is the highest-value 30 minutes in this plan.
3. **Replace silent people.** Anyone with no sign-in by Day 2 is swapped for a standby from a 15-person waitlist. (A late joiner's own 14 days start at *their* opt-in — they add engagement but can't rescue the "12 for 14 days" count, so recruit early.)
4. **Recruit the waitlist** from: placement-cell / college WhatsApp & Telegram groups, final-year classmates, LinkedIn posts, small communities of Android testers (reciprocal testing is fine as a *supplement*; they are less likely to engage with an English-coaching app). **Do not buy testers/installs/reviews** — fake engagement is a policy risk and exactly what "real testers" excludes.
5. Use the **Google Group** so people can join themselves and you never hand-edit lists.
6. Give every tester a **buddy** (you or a teammate, ≤8 testers each) who personally checks in.

---

## 7. The 14-day schedule

*Day 1 = first day all F-items are done. Example: F-items finish Fri 9 Oct → Day 1 = Sat 10 Oct, Day 14 = Fri 23 Oct, apply Sat 24 Oct. If F1–F8 slip, slide the dates — never start the clock with the funnel unfixed.*

| Day | Tester task (≤5 min) | Owner/Dev actions | Release |
|---|---|---|---|
| **1** | Install, sign in, first Daily Talk (3 turns in Hindi) | Kickoff message; watch the ladder hourly; fix blockers same day; screenshot Play tester count | v1.1 live |
| **2** | Daily Talk + **Learn** (2 sentences) · Form Q: "what confused you?" | **Chase every tester with no session** (call/voice note); swap silent people | |
| **3** | **Talk** mode, 3 minutes about your day | Triage feedback; first "you said → we did" post | |
| **4** | **Interview** (3 questions) and read the report | Fix top-3 issues so far | |
| **5** | Daily Talk; **sign out and sign in on another phone or after reinstall** (resume works?) | Check vitals, device-model spread | **v1.2 build** |
| **6** | Learn + Talk | Ladder check; nudge 48 h-silent testers | v1.2 uploaded |
| **7** | **Mid-test survey** (App. A) | Read results; shout-out in group; plan v1.3 | |
| **8–10** | "Use it like normal": ≥1 session/day, any mode, different times/networks | Daily 20-min routine (§9). **Day 10 checkpoint (§8)** | |
| **11** | Themed task: "Mock HR round — *Tell me about yourself*" | Ship polish | **v1.3** |
| **12–13** | 1 session/day · **final survey** + one-line testimonial (optional) | Collect evidence pack | |
| **14** | Thank-you message | **Freeze.** Run Gate (§8). Export evidence | |
| **15** | — | If gate passes: **apply for production** (§12) | |

**Never end or empty the closed test** while waiting for the decision — keep testers opted in and keep the track live.

---

## 8. Gates and go/no-go

**Gate 0 — before Day 1:** F1–F8 done; rehearsal passed; ≥25 opted in.
**Day-10 checkpoint:** ≥20 opted in · ≥15 testers with ≥3 sessions · ≥10 feedback items · ≥2 releases shipped. *If short:* recruit +10, extend the test by 7 days, do **not** apply.
**Gate 14 (apply only if all true):**
- [ ] ≥12 testers opted in continuously ≥14 days (Play Console)
- [ ] ≥12 testers (aim 18) active on ≥5 distinct days
- [ ] ≥150 sessions; every mode used by ≥10 testers
- [ ] ≥3 releases shipped, each with honest notes
- [ ] ≥30 feedback items from ≥12 testers, all triaged, all replied to
- [ ] vitals clean; no open S1 bug
- [ ] evidence pack complete (App. C)

---

## 9. Daily operating rhythm (owner, ~20 min)

1. **Run the report** (App. B, or ask Dev to run it) → who's active, who's silent, new feedback.
2. **Nudge:** anyone with no session in 48 h gets a *personal* message (template A3). Silent 4 days → call.
3. **Triage feedback** into the sheet (App. C); reply to each within 24 h.
4. **Ship:** web fixes deploy immediately via SSH; on release days build/upload the AAB.
5. **Post** the day's "you said → we did" line in the tester group.
6. **Log** the numbers in the evidence log (counts, screenshots).

**Rules:** look at *counts and minutes*, never at what a tester said in conversation — tell testers that (App. A1). Rewards are non-monetary only (shout-outs, the Founding-tester badge). Never ask for ratings.

---

## 10. Feedback → fix → release loop

**Sources:** in-app Help & Feedback (+ post-session card, P1-1) · WhatsApp group · Google Form · Play's tester feedback (the URL/email from F6) · calls.
**Severity:** **S1** blocks use (fix same day) · **S2** hurts (≤72 h) · **S3** polish (batch).
**Release train:** v1.1 pre-Day 1 · v1.2 ≈ Day 5–6 · v1.3 ≈ Day 11. Each = bump `versionCode`, `./gradlew bundleRelease` (JDK 17 — see guide §8.3 gotcha), upload to the closed track, notes below. Web fixes ride along in the notes the day they deploy.
**Notes template:** `What's new in 1.x — Fixed: <what testers reported, plain words>. Improved: <…>. New: <…>.` Only list things that really shipped.
**Honest attribution:** the changelog records the *real* source of every change (tester / owner / own testing). Never credit a tester for something they didn't report — Google reads this.
**Already shipped since the first test** (usable as v1.1 notes if still true when you release): keys-setup guide videos for mobile and laptop; Daily Talk now shows the full conversation; a proper "DuSu is thinking" loader in all modes; interview report always reaches the client + report history; optional level check; desktop layout; canonical `dusu.ranabrothers.online` domain.

---

## 11. Decisions needed from you

| # | Decision | Options | Recommendation |
|---|---|---|---|
| **D1** | **Tester access** | **A** flip `access_phase` → `quota` (everyone rides server keys, 500 req/day, 20-day trial). **B** tester-only: a DB-backed list of emails that ride server keys (~40 lines + deploy; no change for the public). **C** keep 2-key BYOK (guided calls). | **B**, after F2. A is the fallback; C reproduces the failure we just measured. Server cost ≈ 25 testers × ~20 turns/day — fine once keys are healthy. |
| **D2** | Who supplies fresh server keys, by when | new Groq key, Gemini `AIza…` key, OpenRouter refresh | by Oct 7 (F2 blocks everything) |
| **D3** | Roster | confirm ≥25 real Android users + 15 standby; name buddies | you, by Oct 8 |
| **D4** | Day 1 date | Sat 10 Oct (needs F1–F8 by Fri 9 Oct) or Mon 12 Oct | Mon 12 Oct if F2 slips — don't start early |
| **D5** | **Reviewer access** for the eventual production review | keep "no exemption, reviewer does BYOK" (guide §1b) or add a dedicated reviewer demo account to the exemption list | revisit: under B the reviewer account costs nothing and removes the key wall for Google too |
| **D6** | Tester thanks + privacy promise | non-monetary only (shout-out, badge); and you commit to look only at **counts/minutes**, never at conversation content (message A1 says so) | agreed? — if you can't keep the promise, remove that sentence from A1 |

---

## 12. Production-access application — draft answers

*Fill the brackets with real Day-14 numbers. Be specific and honest — including about round 1.*

**Recruitment — how difficult?** "We invited [N] people from [sources]. Round 1 (Sep 21–Oct 5) was weak: of 40 invitees only 15 signed in and 4 completed a session, because [measured causes: API-key setup wall, no follow-up]. For round 2 we [removed the key wall for testers, fixed server keys, ran buddy check-ins]; [N] testers stayed opted in for 14 days."

**Did testers use all features / match expected production behavior?** "[N]/[N] testers used Daily Talk; [n] Talk; [n] Interview; [n] Learn. Median [x] active days, [y] sessions each; [z] total minutes spoken. Sessions are 2–5 minutes, matching expected daily-practice use."

**Feedback received and how collected?** "In-app Help & Feedback and a post-session card, a WhatsApp group, two surveys, Play's tester feedback channel, and calls. [N] items from [N] testers; top themes: [1], [2], [3]."

**Changes made from what you learned?** "Releases 1.1/1.2/1.3: [list each fix with its true source and date]."

**Why production-ready?** "[crash-free %, first-turn success %, open S1 bugs = 0, tester sentiment from final survey, target audience, support & privacy pages live]."

---

## 13. Risks and contingencies

| Risk | Mitigation |
|---|---|
| Opted-in drops below 12 | ≥25 at Day 1, standby list, Google Group, daily buddy check-ins |
| Testers opted in with a different Google account | ask for the "You're a tester" screenshot; add both emails |
| "Item not found" on the opt-in page | wrong account, or Group membership not propagated (allow a few hours) — App. A5 |
| Server keys fail mid-test (all testers hit errors at once) | F2 first; keep a spare key; add a daily live probe; S1 same-day rule |
| Weekday engagement dip | themed tasks Days 5/8/11; 48 h nudge rule; weekend tasks |
| Google rejects again | read the exact reasons; extend 14 more days with a new cohort; keep the evidence; as a Plan B, an **organization** developer account is exempt from this requirement per our earlier notes (`PLAYSTORE_LAUNCH_PLAN.md` §2.4 — *verify with Google before relying on it*; needs a D-U-N-S number and a new Play account) |
| Privacy | tell testers what we measure (counts/minutes), not what they say; keep exports git-ignored (done) |

---

## Appendix A — Tester messages (written for your testers; adapt tone freely)

**A1 · Kickoff (WhatsApp)**
> Hi [name] 👋 I'm launching **DuSu** — an app that helps you speak English with confidence (you talk in Hindi, DuSu replies and teaches the English). I need you as a **tester for 14 days — 5 minutes a day**. Today please:
> 1) On your **Android phone** open [OPT-IN LINK] → tap **Become a tester** (use the same Gmail: [email])
> 2) Tap **Download it on Google Play** → install DuSu
> 3) Open it → sign in with Google → tap **Start Speaking** and say a few sentences in Hindi.
> Please don't leave the testing program for 14 days. I only count *whether* you used the app (sessions/minutes) — I never read your conversations. Stuck? Reply here and I'll call you. Thank you! 🙏

**A2 · Day-2 nudge** — "Hi [name], quick one: did DuSu open for you? If anything was confusing, tell me in one line — I'll fix it today."

**A3 · 48-hour silence** — "Hi [name], I noticed you haven't tried DuSu in 2 days. Takes 3 minutes today: open → Start Speaking → say 3 sentences. If something's broken, tell me what you see 🙏"

**A4 · Mid-test survey (Google Form, Day 7, 6 questions)** 1) Phone model + Android version 2) Which modes did you use? (Daily / Talk / Interview / Learn) 3) What was the most confusing moment? 4) What did you like most? 5) Did DuSu ever feel stuck or slow? when? 6) Would you use DuSu daily? What's missing? (+ optional: one-line testimonial)

**A5 · Troubleshooting**
- *"Item not found / not available"* → open the link with the Gmail that's on the list; wait up to a few hours after being added; join the Group.
- *App shows a browser bar* → known until the Play signing key is added (F4); still works.
- *Mic not working* → Settings → Apps → Chrome → Permissions → Microphone → Allow; DuSu needs **Chrome** as the browser.
- *Stuck on "Thinking…" more than 30 s* → close and reopen; tell me the time so I can check the server.

**A6 · Day 14** — "Thank you [name] — you helped get DuSu to Play. Here's what your feedback changed: [3 bullets]. Please stay in the testing program until I confirm — it matters. 🙏"

## Appendix B — Daily report (read-only SQL, run via SSH)

Save the SQL block below as `report.sql`, then (from the repo root; the testers file is git-ignored). The SQL was extracted from this document and run read-only on 2026-10-06:

```bash
VALS=$(grep '@' playstore-testers.csv | tr -d '\r' | tr 'A-Z' 'a-z' | sed "s/.*/('&')/" | paste -sd, -)
sed "s/@@VALS@@/$VALS/g" report.sql | ssh rooted-ssh 'docker exec -i dusu-db-1 sh -c "psql -q -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -A -F\"|\" -P footer=off"'
```

```sql
SET default_transaction_read_only = on;
\set start '2026-10-10'
-- Q1  status ladder per tester (what the CSV export is): invited → signed in → access → ACTIVE
WITH t(email) AS (VALUES @@VALS@@),
u AS (SELECT lower(email) AS email, id, created_at, last_seen FROM users),
sess AS (SELECT user_id, count(*) n, coalesce(sum(minutes),0) mins FROM session_scores WHERE created_at >= :'start' GROUP BY user_id),
k AS (SELECT user_id, verified FROM user_keys)
SELECT t.email,
  CASE WHEN u.id IS NULL THEN '1-invited-never-signed-in' WHEN coalesce(sess.n,0)>0 THEN '4-ACTIVE'
       WHEN k.verified THEN '3-has-access-never-spoke' ELSE '2-signed-in-stuck-before-access' END AS status,
  coalesce(sess.n,0) sessions, round(coalesce(sess.mins,0)::numeric,1) minutes, u.last_seen::date
FROM t LEFT JOIN u USING(email) LEFT JOIN sess ON sess.user_id=u.id LEFT JOIN k ON k.user_id=u.id ORDER BY 2, 1;

-- Q2  per tester since :start — sessions, distinct active days, minutes, modes used
WITH t(email) AS (VALUES @@VALS@@), u AS (SELECT lower(email) email, id FROM users)
SELECT left(t.email,4)||'***' tester, count(s.id) sessions, count(DISTINCT date(s.created_at)) active_days,
       round(coalesce(sum(s.minutes),0)::numeric,1) minutes, count(DISTINCT s.mode) modes_used
FROM t JOIN u USING(email) LEFT JOIN session_scores s ON s.user_id=u.id AND s.created_at >= :'start'
GROUP BY t.email ORDER BY sessions DESC, active_days DESC;

-- Q3  cohort rollup (owner excluded) — compare with §4 targets
WITH t(email) AS (VALUES @@VALS@@),
u AS (SELECT lower(email) email, id FROM users WHERE lower(email) <> 'david123rana@gmail.com'),
per AS (SELECT u.id, count(s.id) n, count(DISTINCT date(s.created_at)) days
        FROM t JOIN u USING(email) LEFT JOIN session_scores s ON s.user_id=u.id AND s.created_at >= :'start' GROUP BY u.id)
SELECT count(*) testers_signed_in, count(*) FILTER (WHERE n>=1) with_a_session,
       count(*) FILTER (WHERE days>=5) active_5plus_days, coalesce(sum(n),0) total_sessions FROM per;

-- Q4  sessions by mode since :start
SELECT mode, count(*) sessions FROM session_scores WHERE created_at >= :'start' GROUP BY mode ORDER BY 2 DESC;

-- Q5  feedback since :start (no emails)
SELECT to_char(created_at,'MM-DD') day, kind, left(replace(text,E'\n',' '),160) text
FROM feedback WHERE created_at >= :'start' ORDER BY created_at;
```
*Notes:* `usage_daily` stays empty in growth phase (requests are only counted in quota phase), so `session_scores` is the engagement ledger. Learn sessions are not recorded. Q1 is the query behind `playstore-testers-status-*.csv`, limited to sessions since `:start`.

## Appendix C — Feedback sheet, evidence pack, Day-0 baseline

**Feedback sheet columns:** ID · Date · Source (in-app / WhatsApp / Form / Play / call) · Tester (initials) · Type (bug / UX / idea) · What they said · Severity (S1/S2/S3) · Status (new / acknowledged / fixing / shipped / won't-do + reason) · Fixed in (web date / AAB version) · Replied (date).

**Evidence pack (keep outside git, e.g. a private Drive folder):** Play Console screenshots at Day 1 / 7 / 14 (opted-in count, releases, vitals, dashboard counter) · daily CSV exports of the status ladder · the feedback sheet · the "you said → we did" posts · release notes of 1.1/1.2/1.3 · survey results · 3–5 permissioned tester quotes · group-chat screenshots with names hidden.

**Day-0 baseline to read from Play Console (unknown to us today):** testers opted in · which releases are on the closed track · feedback URL/email set? · installs and active devices · the "apply for production" counter text.

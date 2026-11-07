# DuSu - Product Owner + UI Officer audit (2026-10-30)

Owner's ask: *"act like a product owner and UI officer, check and use the full app and make a list of what improvement is needed."*

> **Status update (same day):** every finding below now has a status - DONE / DONE\* / PARTIAL / OWNER / DEFERRED - with its proof in [`DUSU_AUDIT_FIX_PLAN.md`](DUSU_AUDIT_FIX_PLAN.md) (section 1 is the traceability matrix, section 5 what only the owner can do, section 7 the evidence). The numbers in this report are the "before"; `tests/audit/` re-measures them.

## How this was done (so you know what the evidence is worth)

- The **real app** (the working tree = production + the not-yet-deployed key pop-up batch) ran on a scratch Postgres with the **same rollout switches production has** (read-only look at the `settings` table: Home AI, My Day, Practice Room, Job Interview Practice, Grammar Coach, Hindi/English, key screens ON; level check OFF; Install, Notifications, WhatsApp unset = OFF; growth phase = everyone brings their own keys).
- A real Chromium **walked every screen** (35 routes) as five kinds of learner - brand-new, new with keys, active (a month of practice), lapsed, owner - at **390 px phone, 360 px small phone, 1280 px desktop, Hindi, 768/1024/1440 widths**: 127 screen captures, each photographed and measured (overflow, tap size, text size, contrast, names, alt text, console, failed requests).
- It then **used the app with real clicks**: first run of a new account, a Face-to-Face chat, Daily Talk, Learn, a full Interview with its report, My Day forms, the More sheet, the owner dashboard, and the features that are about to go live (Install, WhatsApp, Notifications). Speech and the AI were stand-ins (fake, canned) - so layout and flow are judged here, **never AI quality or Hindi quality**.
- The **live public page** was loaded like a visitor under throttled CPU and network (read-only).
- Screenshots + numbers: `~/.cache/dusu-audit-shots/` (300 files, `results-walk.json`, `live-perf.json`, `flows-log.json`). Harness: `tests/audit/` (README inside). Re-runnable.
- **Technical health is clean:** 0 console errors, 0 HTTP errors, 0 failed requests across all 127 screen loads. Every problem below is a *product/design* problem, not a crash.

## Verdict

DuSu looks premium and the building blocks are strong (My Day, Grammar Coach, Job Interview Practice, the Journey roadmap, honest "AI-estimated" labels, keyboard accessibility). But **a new learner has to get through three walls before the first spoken sentence** - a five-screen "bring your own free AI keys" setup, a four-card rewards lecture, and a Home with ~20 blocks - and **there is no way to pay and no way to measure where people drop**. Fixing the first-run path and the weight of the first visit will move the numbers more than any new feature.

Legend: **P0** stops growth or trust - **P1** hurts the core experience - **P2** polish. Effort: S = hours, M = days, L = a week or more. "Verified" = reproduced/measured here.

---

## P0 - fix first

### P0-1  The first screen after sign-in is a key-setup wall  *(verified, effort M-L)*
- A brand-new account lands on **Keys** (`newbie-390__landing.png`, `-full.png`): **4,046 px = five phone screens**; the first input box is more than 1.5 screens down. Before it: a long intro, two video thumbnails, a 7-step guide.
- It says **"about a minute"** four times (code lines 3032, 4966, 8493, 11378) - but every key means signing up on another website. The real first-time cost is minutes, and a learner who cannot do it in a minute feels they are failing.
- English-only and jargon-heavy ("API key", "provider", Groq / Gemini / OpenRouter) for learners who may be A0-A2 and Hindi-first.
- **The primary-looking buttons are three identical "Save key" buttons**; the real first action, "Get free key ↗", is an 11.5 px link (82x17 px tap area).
- Step 7 promises **"your 2-minute level check"** - but the level check is OFF in production, so the learner lands on Home instead.
- In the growth phase every non-owner learner must pass this. **Nothing measures the drop-off** (see P1-10), but this is the highest-risk screen in the product.
- **Fix, in this order:** (1) let a new learner speak first - a short taste (3-5 turns) before any key is asked (needs DuSu's own keys healthy again); (2) if keys must stay first: **one key to start** (second key later), **one paste box that recognises the provider by its prefix**, a huge "Get free key" button that opens the provider and brings them back; (3) Hindi steps/video and honest time ("about 5 minutes the first time"); (4) show "key 1 of 2"; (5) put the long guide *below* the box, collapsed; (6) remove the level-check promise.

### P0-2  There is no way to pay  *(verified, effort S now / L later)*
- "See plans" (in every limit pop-up) and More → Plans lead to **Choose your plan → Proceed → "payment coming soon"**. The long-term idea ("learners slowly move to plans") cannot start.
- The plans page is **stale and vague**: no mention of Job Interview Practice, Grammar Coach, My Day, Practice Room; "higher daily limit / more requests per day / unlimited use" are not concrete; **no Free column** to compare (`active-390__subscribe.png`).
- **Do now (S):** replace Proceed with **"Reserve my plan / Notify me"** that stores intent (+ phone or email). It gives demand and price-sensitivity data and is honest. **Then (L):** UPI/Razorpay. Rewrite the three plans in outcomes ("20 min of AI talk a day", "all practice rooms"), add the Free column.

### P0-3  The first visit is heavy; every open pays a tunnel round trip  *(verified on the live site, effort S-L)*
- Cold first visit, signed out (login screen): **2.3 MB, 13 requests**. **`/logo.png` alone is 1.7 MB (74%)** and is what the first paint waits for. The HTML is 1.12 MB raw / **306 KB compressed**, then ~300 KB of Google scripts/iframes/fonts.
- Measured (4x slower CPU): unthrottled load 3.5 s, LCP 3.7 s - **Slow 4G: LCP 12.1 s - 3G: LCP 46 s**. Main thread blocked ~0.8 s on the 4x CPU during load.
- The HTML has **no cache validators** (`cf-cache-status: DYNAMIC`, no ETag/Cache-Control) and the service worker is **network-first with no timeout**, so every launch waits for ~1-1.3 s tunnel time-to-first-byte (50 ms when asked directly) + ~300 KB. (Repeat opens looked fast in the lab only because Chrome's throttle does not reach the service worker's own fetches - on a real slow phone the wait is real.)
- **Fix:** (S) stop using the 1.7 MB logo - the 60 KB icon already exists, a 10 KB WebP is better: saves 1.7 MB on the very first impression; (M) service worker "stale-while-revalidate" for the shell + an ETag, with a small "new version - tap to update" bar; (M) self-host the two fonts (`font-display: swap`), load the Google sign-in script only on the login screen; (L) split the single 14,700-line file so the first screen loads only what it needs.

### P0-4  (known, not a UI fault) DuSu's own AI keys are not healthy
Found earlier today: Gemini returns 403 ("free tier not available for this project"), Groq key rejected, OpenRouter free pool busy. Until the owner replaces them, the owner / free-access accounts and any "taste first" idea cannot work. See `CLAUDE.md` section 22.

---

## P1 - core experience

**P1-1  Home is overloaded** *(verified, M)* - `active-390__home-full__s2..s5.png`: ~**20 blocks, 3,570 px** (4-5 screens). 12 icon tiles **and** banner cards for the same features (Practice Room = "Presentation coming up?", My Day, Job Interview Practice, Grammar Coach, Career Path = "Your future", Journey/League again as "Your progress"). A second and third big gradient button ("Set your goal", etc.) compete with **Start Speaking**. A technical **"AI keys - 0 requests today"** card sits in the feed. A **website footer** (Product / Rana Brothers / social icons / "Modes (coming soon)" / "Back to top") closes an app screen. **Fix:** hero + Start Speaking → ONE "today" card (the next best action) → 8 tiles → the rest behind More/Journey. Show the keys card only when something needs attention. Drop the footer from the app (keep Privacy/Terms/Delete my data in More).

**P1-2  One feature, many names** *(verified, S)* - Face-to-Face = "Talk" = "Face to Face Talk" = "Face to Face English Talk" = "Confidence Talk" (session title, footer). Learn = "Learning Mode" = "Convey your thoughts in English". "Interview Prep" vs "Job Interview Practice" vs "Practice Room". "Daily" tab vs "Daily Talk". **Fix:** one name per feature, used in nav, tile, screen title, report, footer, Know-About.

**P1-3  Three different "start speaking" doors, no guidance** *(M)* - Home "Start Speaking" (Home chat, Hindi/English), the **Daily** tab (Hindi-first Daily Talk), Practice → **Talk** (English only). A fresher cannot tell which to use. **Fix:** a day-1/2/3 golden path, one recommended action, each door named by outcome ("Chat about your day", "Practise English only", "Mock interview").

**P1-4  Empty states are dead ends** *(verified, S-M)* - Interview Reports (`interview-reports.png`: one grey line, 90% blank), Grammar Coach (Overview/Mistakes/Sentences/Practice), Career Path, "My interviews / resumes / job descriptions", "No practice yet". None has a button for the thing it is waiting for. **Fix:** icon + one sentence + one primary button ("Start an interview").

**P1-5  First-run overlays stack up** *(verified, S)* - after the keys, a **4-card "How DuSu rewards you"** lecture (Speaker Rank / League / Achievements & Season Awards / Confidence Check) opens **before the learner has spoken** (`flowA__after-keys.png`). A brand-new learner also gets the mood check-in and **"Where we left off - You were doing really well."** (`keyed-390__home-full__s4.png`) - false when they have done nothing. **Fix:** show the rewards intro after the first finished session (or as a one-line tip); hide "Where we left off" until there is history.

**P1-6  A short chat ends with a red "Speaking Score 0 (-64)"** *(verified, S)* - `flowB__f2f-result.png`: a 12-second chat shows XP +5 and a red 0 with -64. Discouraging. Say "Too short to score - talk for a minute to get a score." A Daily Talk with zero turns says "Session saved." (`flowC__daily-finish.png`).

**P1-7  Offline / connection copy is developer language** *(verified, S)* - "**Connection error - Is the server running?**" twice on screen, no retry (`a11y__offline-start.png`). Say "No internet. Your chat is safe - check your connection" + a Retry button.

**P1-8  Cold deep-link race: "isn't available" even though it is** *(verified 6 of 6, S)* - opening `/my-day`, `/resume-interview` or `/practice-room` as the **first** load on a device with no cached state shows "My Day isn't available for this account" / "Job Interview Practice isn't available yet" / "Practice Room isn't available yet" and drops the learner on Home (`race.cjs`). Hits a new phone, cleared data, or a reminder-notification tap on a fresh install. **Fix:** wait for `/me` before checking feature flags.

**P1-9  The retention loops are built but OFF** *(M after a phone test)* - Install prompt, Notifications (push), WhatsApp community: no switch rows in production, 0 push devices. Day-1/Day-7 return currently depends on the learner remembering. Pre-checked here: the three sheets look good and are honest ("members can see each other's phone numbers"). **Plan:** real-phone test → switch on in this order: Install → Notifications → WhatsApp.

**P1-10  No product analytics** *(M)* - no funnel at all. You cannot see how many reach the Keys screen, save key 1 / key 2, say a first sentence, return on Day 1 / Day 7, open the plan card, tap Proceed. Add ~10 server-side counters before changing P0-1 so the change can be judged.

---

## P2 - UI system and polish

| # | Finding (verified) | Fix | Effort |
|---|---|---|---|
| UI-1 | **Old-style numerals in the serif font**: `0` looks like "o" ("o XP" on Ranks, "o (-64)"), `1` looks like "I" - the interview report headline **"71" reads "7I"** (`flowE__interview-report.png`); prices and XP descend below the line | `font-variant-numeric: lining-nums tabular-nums` on number elements, or Inter for numbers | S |
| UI-2 | **Text too small**: bottom-nav labels 10.5 px, header chips 10-11 px, tile labels 11.5 px, More-row descriptions 11.5 px; 36 distinct font sizes, 100+ declarations <= 12.5 px; Devanagari looks smaller still | floor 12-13 px; a 6-step type scale | M |
| UI-3 | **Header = six items on every screen** (logo, Beta, Day N, ♀, avatar, alias). At 360 px the avatar squashes to an **oval** and the alias is cut ("BoldSpar"); with the Install pill (when on) it gets worse; at 768/1024 the name/alias/♀ clip. The **♀ button does nothing useful** (the male option is hidden; it only says "Hi, I'm DuSu") | logo + one avatar button; alias inside Profile; remove ♀; hide Beta/Day on phone | S |
| UI-4 | **Tap targets under 44 px**: logo button 58x31, ♀ 34x28, alias 84x24, Back buttons 38x38 / 91x38, language pills 34 px high, filter chips 38 px, footer links 15-26 px high, "Get free key" 82x17 | min 44x44 | S |
| UI-5 | **My Day header wraps on phones**: bell, then the gear **alone on its own row**, then the language pill on a third row (~115 CSS px wasted before the tabs); the first tab "आज" is Hindi beside English tabs; the round "+" duplicates the big "+ Add" button and **covers row edit/delete icons** while scrolling | one header row; one add button | S |
| UI-6 | **Three icon styles**: SVG line icons (nav, tiles), emoji (More rows, cards, chips, ⬜ checkboxes, status) | one set (SVG), emoji only for mood | M |
| UI-7 | **Brand colours drift**: gold score ring on the interview report vs indigo everywhere; the CSS variable `--gold` holds indigo; 112 hard-coded hex + 145 rgba values beside ~15 tokens | tokens only | M |
| UI-8 | Grammar Coach tab "Sentences" cut to "Senten..." at 390 px; Home's Hindi/English pill is half hidden behind the bottom nav on the first screen | shorter label / scroll hint | S |
| UI-9 | **Practice hub mixes two designs** (3 tall glowing cards + 3 centred-heading pills); desktop shows "START HERE / MOST LOVED" badges that **mobile hides** - the phone user gets no recommendation | one pattern; show the recommendation on mobile | S-M |
| UI-10 | Desktop Home: cards of four different widths (~420 / 780 / 930 px); 768-1199 px gets the phone column with a clipped header | one column width; tablet header | S-M |
| UI-11 | Achievements: 24 locked badges all say just "Locked" - no "how to earn" | show the requirement | S |
| UI-12 | Ranks lists **every** account incl. 0-XP; podium can show 0 XP | only this week's active | S |
| UI-13 | Journey: unlabeled 5-bar chart, "CONFIDENCE STARS 1/7", "TODAY 8/5", "Goal: job" (raw value), a lone "💪 78%" chip, "YOU TODAY" repeating the Day-1 quote | label or remove | S |
| UI-14 | Owner dashboard on phone: long paragraphs squeezed beside each select (a 9-word column) | stack select under text | S |

## Copy and content

- Interview setup is **pre-filled "Frontend Developer"** for everyone (`#role` has a value, not a placeholder).
- Hindi register mixes **आप** ("लगाइए / बोलिए / आपके") with **तुम** ("बताओ / तुम्हारी") on the same chat screen. Native read needed.
- Time shown as "8:30 PM" and "7:00 pm" in one list. "1 sessions" (plural bug, league rows, code line 7322).
- Footer: **"Modes (coming soon)"** and stale names ("Confidence Talk").
- "**DuSu keys / Mode - Personal or Office (own keys)**" on More and the Keys screen: internal words, meaningless to a learner. Call it "My AI keys".
- "**Beta Testing · Unlimited**" on tablet/desktop vs "free keys have daily limits" in the pop-ups and the plan pitch - one of them is wrong.
- New-learner chips "मेरा routine / मेरी progress" mean nothing on day 1 - use "Where do I start?" / "Interview practice".
- Hindi/English only changes the **new** features. Practice, Journey, Ranks, Profile, Keys stay English even with हिंदी selected (by design, section 11) - set expectation or translate the top strings per screen.
- Roman Hinglish (Grammar rules, Learn) next to Devanagari Hinglish (Home, My Day): pick one rule per feature and keep it.

## Accessibility

- **Good:** all 28 keyboard stops on Home show a visible focus ring, in a sensible order; 0 unnamed controls; every image has alt; reduced-motion respected (19 rules); zoom not disabled.
- **Gaps:** secondary text at **4.46:1** (just under AA 4.5) on many 13 px labels; **dark theme only** (hard in sunlight on budget LCDs); emoji-only mood buttons; **not tested:** TalkBack, Android large-font setting, iPhone Safari.

## Engineering risk worth knowing (not user-visible)

- 148 `innerHTML` uses in the older modules (the newer modules use a safe DOM builder) - a surface for learner-controlled text.
- One 14,700-line file: every change touches everything.

## What is already good - keep it

Premium, consistent dark identity; warm Hinglish Home greeting and a big **Start Speaking**; honest "AI-estimated, not an exact measurement" labels; clear privacy copy in Job Interview Practice; the **Journey worlds** roadmap with a locked next-world teaser; the calm key pop-up; **My Day** (tasks + habits + goals + repeating reminders) is rich and consistent; the Grammar rules page is excellent, tailored Hinglish content; Know About DuSu explains every feature in the learner's own language; offline reload works (the service worker serves the last shell); zero technical errors.

## Not checked here - needs a real device or the real world

Real phones (TWA/PWA status bar and notch - the Home chat's top bar sits flush at the very top edge, mic permission, TTS voices, battery), real AI replies and latency, native Hindi quality, push delivery, payments, TalkBack, large fonts, iPhone Safari.

## Suggested order

1. **This week (hours each):** logo 1.7 MB → small (P0-3); lining numerals (UI-1); header slim-down + oval avatar + dead ♀ (UI-3); rewards lecture deferred (P1-5); "Where we left off" for zero history; "1 sessions"; footer clean-up; connection-error copy (P1-7); deep-link `/me` wait (P1-8); Interview role placeholder; locked-badge hints; Reserve-my-plan button (P0-2).
2. **Next 2 weeks:** Keys wall redesign (P0-1) **after** the ~10 analytics counters (P1-10) are in; Home restructure (P1-1); one name per feature (P1-2); empty states with buttons (P1-4); My Day header; type scale + 44 px targets.
3. **Month 2:** service-worker shell caching + fonts + lazy modules (P0-3); payments; real-phone test then Install → Notifications → WhatsApp (P1-9); icon/colour token clean-up.

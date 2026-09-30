# DuSu — Brand & Marketing Plan (Rana Brothers)

> **Status:** branding implemented in the product on 2026-09-30. Marketing execution is the
> owner's to run. This doc is the decision record + the playbook.
>
> **One-line frame:** *DuSu* is the product. *Rana Brothers* is who makes it. *David Singh
> Rana* is the person legally responsible for it.

---

## 1. Why Rana Brothers, and what it may and may not say

### The constraint

The owner is employed full-time, and the employment terms do not allow starting or running a
competing/registered business. RuralRoot Cloud is a registered company, but DuSu is not its
product and must not be marketed as if it were. So DuSu ships under **Rana Brothers** — the
owner and his brother — which is a *name two people build under*, not a legal entity.

### Brand architecture (locked)

| Layer | Name | Used for |
|---|---|---|
| Product | **DuSu** | The app itself, the icon, the Play listing title, the domain |
| Maker brand | **Rana Brothers** | Credit line, footer, socials, portfolio, outreach, invoices-later |
| Legal operator | **David Singh Rana** | Privacy Policy, Terms, Play Console developer legal name |
| Identifier form | **ranabrothers** | `ranabrothers.online`, `support@ranabrothers.online`, `@ranabrothers` handles |

Display form is always the two-word, title-cased **Rana Brothers**. The squashed
`ranabrothers` form is only ever an identifier (domain, email, handle).

### Language rules — non-negotiable

These keep the positioning honest and keep it clear of the employment problem.

**Say:**
- "A Rana Brothers project."
- "Built by Rana Brothers — two brothers from India."
- "An independent project by Rana Brothers."
- "Rana Brothers is an independent two-person project, not a registered company." *(already in
  Privacy + Terms)*

**Never say:**
- "Rana Brothers Pvt Ltd" / "Ltd" / "Inc" / "LLP" / "Corporation"
- "our company", "our firm", "our agency", "our team of N engineers"
- "registered in India", a CIN/GST number, or an office address
- anything that implies DuSu is a RuralRoot Cloud product, or that RuralRoot endorses it
- any claim that the owner's employer is involved

**Framing to use if anyone at work asks:** DuSu is a personal learning project built in own
time under a family name, published free, with no company and no revenue. That is currently
true and the language above keeps it true. **Re-read the employment agreement's
moonlighting / IP-assignment clauses before the first rupee of revenue** — the moment money
changes hands the framing above stops covering it. See §9.

### The RuralRoot path (future, not now)

RuralRoot Cloud stays out of DuSu's public face entirely. If DuSu later needs a legal entity
to invoice a client or take payments, the intended route is a **contract between RuralRoot
Cloud and the client**, with Rana Brothers as the build team — not a rebrand. Nothing in the
product should pre-announce that.

---

## 2. What changed in the product (done)

| File | Change |
|---|---|
| `backend/test_client.html` | Login card now reads **"A Rana Brothers project"**; footer brand column gains the same line; the footer's third column is retitled **Rana Brothers**; copyright is now `© 2026 Rana Brothers · DuSu · Made with ♥ in India`; Help-screen support address swapped |
| `backend/test_client.html` | Footer legal links were dead `<a>` tags — **Privacy**, **Terms** and **Delete my data** now open the real pages, and **Contact** opens the in-app Help & Feedback screen. Traffic from an ad has to be able to reach these. |
| `backend/privacy.html` | "Who runs DuSu" now names Rana Brothers as the brand *and* David Singh Rana as the responsible operator, and states plainly that Rana Brothers is not a registered company |
| `backend/terms.html` | Same framing in the opening paragraph; contact address swapped |
| `backend/account-deletion.html` | Contact address swapped |
| `PLAYSTORE_SUBMISSION_GUIDE.md` | Support email swapped (4 places) + an explicit warning **not** to put "Rana Brothers" in Play's *developer legal name* field, which Play verifies against government ID |

**URLs were deliberately left alone**, per instruction: `dusu.ruralrootcloud.com` remains the
host in `android-twa/.../strings.xml`, `docker-compose.yml`, `cloudflare/TUNNEL.md` and the
OpenRouter `HTTP-Referer` in `backend/app/config.py`. The only remaining `ruralroot` strings
in the repo are those infrastructure references — nothing a user sees. §8 covers cutting the
domain over when you're ready.

---

## 3. ⚠️ Do this before you send anyone to the app

`support@ranabrothers.online` is now printed in the app, in the Privacy Policy, in the Terms
and on the account-deletion page. **It does not exist yet.** A support address that bounces is
a Play policy problem (Play mails it to verify) and kills trust with the first user who tries it.

**Cloudflare Email Routing — free, ~5 minutes:**

1. Cloudflare dashboard → zone **ranabrothers.online** → **Email** → **Email Routing** →
   *Get started*.
2. Cloudflare offers to add the required MX + SPF records automatically — accept.
3. **Destination addresses** → add your everyday Gmail → click the verification link Cloudflare
   mails you.
4. **Routing rules** → *Create address* → `support@ranabrothers.online` → *Send to* → that Gmail.
5. Optional but worth it: also route `hello@`, `david@`, and set a catch-all to the same inbox.
6. Test: mail `support@ranabrothers.online` from a different account and confirm it lands.
7. To **reply as** that address (so users don't see your personal Gmail): Gmail → Settings →
   Accounts → *Send mail as* → add `support@ranabrothers.online` via SMTP. Cloudflare Email
   Routing is receive-only, so use Gmail's SMTP with an app password for sending.

Until step 6 passes, do not submit the Play listing with the new address and do not run ads.

### Also: Cloudflare is obfuscating the address on the live site

Cloudflare's **Scrape Shield → Email Address Obfuscation** is ON for the zone, so the address
is rewritten in the served HTML to `[email protected]` plus a decode script. Browsers with JS
show the real address, so ordinary users are fine — but anyone reading the page without JS
(and any scraper, or a reviewer viewing source) sees the placeholder. This is pre-existing
behaviour, not new: it was doing the same to the old address.

Verify with `curl -s https://<host>/privacy | grep __cf_email__` — a hit means it's on. If you
want the address to render literally, turn it off in the Cloudflare dashboard → the zone →
**Scrape Shield** → *Email Address Obfuscation* → Off. Trade-off: it exists to reduce spam
harvesting, so leaving it on is defensible. Decide once, and keep the Play Console support
email field (which is separate and never obfuscated) correct regardless.

---

## 4. Who we're selling to

Unchanged from the product thesis, sharpened for outreach.

**Primary wedge — Indian final-year students and freshers in placement season.** They *know*
English grammar. They freeze when they have to speak it to a human under pressure. They have a
budget Android phone, patchy data, and a placement drive in 4–10 weeks. They are already
anxious and already searching.

| Segment | Where they are | What they actually want | The line that lands |
|---|---|---|---|
| Final-year / placement (primary) | College WhatsApp + Telegram groups, r/developersIndia, LinkedIn, YouTube "HR interview questions" | To not blank out in the HR round next month | "Practice the HR round out loud tonight. Free." |
| Freshers 0–2 yrs | LinkedIn, Instagram reels | To stop sounding nervous on calls | "You know English. You just freeze. That's a different problem." |
| Non-metro learners | YouTube, Instagram, Hindi-first content | To think in English instead of translating | "Bolna Hindi mein, sunna English mein." |
| Working professionals | LinkedIn | Confidence in meetings/standups | "15 minutes of speaking practice before your next standup." |
| College TPOs / training cells (B2B2C, later) | LinkedIn, direct email | A free tool to hand 300 students | "Free speaking practice for your whole batch. No licences." |

**Not our user (say no to these to stay sharp):** IELTS/TOEFL score-chasers, absolute
zero-English beginners, kids.

---

## 5. Positioning & message

**Category:** not an English course. A **speaking-confidence companion**.

**Positioning statement:**
> For Indian students and freshers who know English but freeze when they have to speak it,
> DuSu is an AI speaking companion you talk to out loud — it remembers you, adapts to your
> mood, and runs realistic mock interviews with a scored report. Unlike grammar apps that make
> you tap answers, DuSu makes you *speak*, because speaking is the thing you're actually
> afraid of.

**Message hierarchy** (use in this order, always):

1. **The pain, in their words** — "You know English. You freeze when you have to speak it."
2. **The mechanism** — "You talk out loud. DuSu listens, replies with a voice, remembers you."
3. **The proof** — mock interview → scored report on grammar/fluency/confidence + a rewritten
   better answer.
4. **The removal of friction** — free, no payment, works in the browser, installs as an app.

**Taglines**
- Master: **"Speak with confidence."** (already the brand line — don't replace it)
- Campaign: *"You know English. Now say it out loud."*
- Hindi/Hinglish: *"English aati hai. Bolne mein darr lagta hai. Wahi theek karte hain."*

**Differentiator to hammer:** DuSu *remembers you between sessions* and speaks first. Duolingo
does not. That's the demo that makes people share it.

---

## 6. Channels — zero budget, in priority order

The whole stack is $0. Marketing should start $0 too. Do 1 and 2 properly before touching 3.

### Tier 1 — do these first

**1. Demo video (the single highest-leverage asset).**
60–90 seconds, phone screen recording with real audio: open DuSu → it greets you by name from
memory → you answer an interview question out loud → the scored report appears. No slides, no
voiceover explaining features. The product *is* the ad, because hearing it talk back is the
thing nobody expects. Cut three versions: 90s (YouTube/LinkedIn), 30s (Instagram/Shorts), 15s
(hook only). There is already a tutorial video embedded on the keys screen — same production
bar is fine.

**2. College WhatsApp / Telegram groups.** Your actual distribution. One message + the 30s
clip + the link, sent to placement groups by students who already use it. Do not blast — get
5 real users first, ask them to post it. Seed target: 3 colleges.

**3. LinkedIn, posting as yourself, not as a brand page.** Personal accounts reach; new
company pages don't. Post the build story — "my brother and I built an AI that you talk to, to
fix the thing I personally freeze at" — with the demo video. Sign off *"— Rana Brothers"*.
2 posts/week. Placement season is the window.

### Tier 2 — after the demo exists

**4. r/developersIndia, r/india, r/Btechtards.** These subreddits eat self-promo alive unless
you lead with the build, not the product. Title as a build log: "I built a voice AI that runs
free mock HR interviews — here's what I learned about latency". Answer every comment. Link in
the body, not the title.

**5. YouTube Shorts / Instagram Reels.** Format that works for this product: *"Answer this
interview question in 10 seconds"* → freeze frame → DuSu's scored answer. Repeatable weekly,
cheap to make, and each one is a mini-demo.

**6. Quora / Google.** "How to improve English speaking without a partner" has steady Indian
search volume. Long, genuinely useful answers with one link at the end.

### Tier 3 — once there's traction

**7. College training & placement cells (B2B2C).** Cold email TPOs with: free, no licence, no
install, works on any Android, here's a 90-second video. One yes = 300 users. This is the
channel with the best ratio in the whole plan and the one that eventually justifies a
contract.

**8. Micro-influencers** in the placement-prep niche (10–50k). Barter, not cash: free
unlimited access + credit.

### Not now
Paid ads (no budget, no conversion data yet), Product Hunt (wrong audience — it's Indian
students, not SF founders), a press push (nothing to report yet).

---

## 7. Launch sequence

| Phase | Window | Goal | Done when |
|---|---|---|---|
| **0 — Make support real** | Day 0 | `support@ranabrothers.online` receives mail | §3 step 6 passes |
| **1 — Close friends** | Week 1 | 10 real users, watch them use it | 10 sign-ups; every crash/confusion logged |
| **2 — Assets** | Week 1–2 | Demo video (3 cuts), 6 screenshots, one-paragraph pitch, `@ranabrothers` handles created | Assets exist and the footer socials are wired to them |
| **3 — Play listing** | Week 2–3 | App live on Play under developer *David Singh Rana* | Review passed |
| **4 — Colleges** | Week 3–6 | 3 college groups seeded, 150 users | 150 sign-ups, 30% day-2 return |
| **5 — Public content** | Week 4+ | LinkedIn + Reddit + Shorts cadence | 2 posts/week sustained for a month |
| **6 — TPO outreach** | Week 8+ | First institutional user | 1 college using it with a batch |

Sequencing matters: **do not** run Phase 5 before Phase 1. Sending 500 strangers at an app
that has an unverified bug is the one mistake that's expensive to undo.

---

## 8. Domain cutover (deferred, per instruction)

URLs stay on `dusu.ruralrootcloud.com` for now. When you want the public URL to match the
brand, the target is `dusu.ranabrothers.online` (Cloudflare zone already yours — see
`DUSU_LOCAL_CLOUDFLARE_PLAN.md`, which already assumes that hostname). It is **not** a find-
and-replace; it touches four things that must change together:

1. `android-twa/app/src/main/res/values/strings.xml` — `launchUrl`, `hostName`,
   `asset_statements` → then rebuild and re-publish the APK/AAB.
2. `/.well-known/assetlinks.json` must be served from the new host (it already is, by the
   backend) — re-verify with `curl`, or the TWA loses full-screen and shows a URL bar.
3. Google OAuth — add the new origin to *Authorised JavaScript origins* in Google Cloud
   Console **before** cutting over, or sign-in breaks for everyone.
4. `backend/app/config.py` — the OpenRouter `HTTP-Referer` header.

Do it **between** Play releases, never mid-review, and keep the old hostname resolving for at
least 30 days so installed TWAs don't break.

---

## 9. Money, and the line you can't cross casually

Today DuSu is free and takes no payments, which is what keeps the "personal learning project"
framing accurate. The moment you charge — subscriptions (the `#subscribe` screen already has
₹299/₹599/₹899 tiers drafted) or client work — three things become true at once:

1. It stops being a hobby for employment-agreement purposes. **Re-read the moonlighting and
   IP-assignment clauses first**, and if it's ambiguous, get written permission or route the
   contract through RuralRoot Cloud. This is the single highest-risk item in this plan and it
   is worth a one-hour conversation with someone who has read your actual contract.
2. You need an entity or at least a proprietorship to invoice and to satisfy Play's payment
   requirements. "Rana Brothers" cannot receive B2B payment as-is.
3. Play requires the subscription to be sold through Play Billing for in-app digital goods.

So: **keep it free while marketing.** Free is also the strongest wedge you have against every
paid competitor, and the current $0 cost base means free costs you nothing but quota.

---

## 10. Metrics

Instrument nothing new for now — `/admin/overview` already reports users, sessions, minutes
and words per user, which covers the first four rows.

| Metric | Why it's the one that matters | First target |
|---|---|---|
| **Day-2 return rate** | A companion people don't come back to is a failed companion. The single best signal. | 30% |
| Completed first session | Measures whether onboarding + BYOK friction is survivable | 60% of sign-ups |
| Median session minutes | Speaking time is the product | 5 min |
| 7-day streak holders | The retention engine working | 10% of actives |
| Sign-ups per channel | Tells you which of §6 to double down on | — |
| Turn latency | Product plan's killer metric; >1.2s and the conversation dies | < 800 ms |

Review weekly. Kill any channel that hasn't produced a returning user in three weeks.

---

## 11. Assets still to make

- [ ] **`support@ranabrothers.online` routing** — §3. Blocking everything else.
- [ ] Decide on Cloudflare email obfuscation (§3) — on = spam protection, off = the
      address renders literally for non-JS readers
- [ ] Demo video, 3 cuts (90s / 30s / 15s)
- [ ] 6 Play screenshots + feature graphic (`PLAYSTORE_SUBMISSION_GUIDE.md` has the specs)
- [ ] `@ranabrothers` on LinkedIn / Instagram / X / YouTube — **then wire the footer social
      icons**, which are currently decorative `<a>` tags with no `href`. Don't invent URLs
      before the handles exist.
- [ ] A real **About** page or section — the footer's "About" link was removed rather than
      left dead; a one-paragraph "two brothers, one problem" story is worth having before the
      LinkedIn push, and it's the page that makes Rana Brothers feel real to a TPO.
- [ ] One-paragraph pitch, copy-pasteable into a WhatsApp group
- [ ] A cold-email template for TPOs

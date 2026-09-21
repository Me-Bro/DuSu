# DuSu — Play Console Submission Guide

Fill-in-the-blanks reference for uploading DuSu to Google Play. Every answer below was checked against the actual code in this repo, not assumed. Work top to bottom — the order matches how Play Console gates things.

---

## 0. Facts you'll be asked for repeatedly

| Field | Value |
|---|---|
| App name | `DuSu` |
| Package / Application ID | `com.dusu.app` |
| Version | `versionName 1.0`, `versionCode 1` |
| Developer legal name | David Singh Rana |
| Support email | support.ruralrootcloud@gmail.com |
| Website | https://dusu.ruralrootcloud.com |
| Privacy policy | https://dusu.ruralrootcloud.com/privacy |
| Terms of service | https://dusu.ruralrootcloud.com/terms |
| Account deletion page | https://dusu.ruralrootcloud.com/account-deletion |
| Category | Education |
| Free or paid | Free |
| Contains ads | No |
| In-app purchases | No |
| Upload key SHA-256 | `EF:02:68:27:13:49:FE:BA:D0:45:00:60:E6:90:6E:60:75:D4:9B:1A:E5:FD:CE:68:1D:35:AE:19:82:CD:62:0D` |
| AAB to upload | `android-twa\app\build\outputs\bundle\release\app-release.aab` |
| Keystore | `android-twa\app\dusu-release.jks` (alias `dusu`) — **back this up off this machine** |

---

## 1. 🚨 Two blockers to handle BEFORE you submit

### 1a. Play App Signing will break the full-screen mode unless you act

This is the same class of bug that caused the URL bar you just fixed, and it **will come back** for Play-installed users if skipped.

When you enroll in Play App Signing (default for new apps), Google **re-signs** your app with its own key. Users installing from Play get a build signed with the *Play app signing key*, not your upload key. Your server currently only publishes the upload key's fingerprint — so Play-installed builds will fail Digital Asset Links verification and show the browser bar again.

**Fix, after your first upload:**
1. Play Console → **Test and release → Setup → App signing**
2. Copy the **"App signing key certificate" SHA-256** fingerprint
3. On the server, append it to the existing value (comma-separated — keep the upload key too):
   ```bash
   ssh rooted-ssh 'cd ~/Desktop/DuSu && nano backend/.env'
   # make the line read:
   # ANDROID_CERT_SHA256=EF:02:...:62:0D,<PLAY_APP_SIGNING_SHA256>
   ssh rooted-ssh 'cd ~/Desktop/DuSu && docker compose up -d --force-recreate backend'
   ```
   **`--force-recreate` is required.** `restart` reuses the container's existing
   environment, and plain `up -d` is not enough either: Compose compares service
   *config*, not the contents of `env_file`, so it prints "Starting" and keeps the old
   values. This was hit for real while enabling the super-admin portal — the variable
   was correct on disk and the endpoint still behaved as if unset.
4. Verify: `curl https://dusu.ruralrootcloud.com/.well-known/assetlinks.json` shows **both** fingerprints.

### 1b. The reviewer cannot get into the app — you must give them access

DuSu requires Google Sign-In, and in `access_phase = "growth"` (the current default) every normal user must add **2 verified AI provider keys** before anything works. A Google reviewer with a fresh account hits that wall and will reject the app as broken/unusable.

⚠️ **Do NOT use the office/"free access" allowlist for this.** `is_office()` in
`main.py` means *"must bring own keys"*, not "free access" — `resolve_keys()` returns
`keys_required` for anyone on that list. Adding the reviewer there makes it worse, not
better. (The admin UI label has been corrected to "Require own keys (BYOK)", but the
function name still reads backwards.)

The only two things that actually exempt an account:

- **`UNLIMITED_EMAILS` in `main.py`** — currently an empty set. Adding the demo
  account's email there gives it unlimited use of the server's keys, with no BYOK and
  no quota. Affects exactly that one address; testers still BYOK as intended. Needs a
  code change + deploy.
- **`access_phase = "quota"`** — flipped in the Admin dashboard. Drops the BYOK
  requirement for *everyone* for the duration of review, which is a bigger blast
  radius than you probably want.

Either way the reviewer still needs an account to sign in with, so create a dedicated
demo Google account and put its credentials in the **App access** section.

**Also confirm the server's own keys work before review starts.** Whichever route you
pick, the reviewer rides the default chain — and if it is down (as it was on
2026-09-21: Groq revoked, Gemini expired, GitHub retired) the reviewer sees an app
that cannot answer. Check `curl https://dusu.ruralrootcloud.com/health` and compare
`available` against `cooling`. Note a Gemini `AQ.`-prefixed value is a short-lived
OAuth token, not an API key — use an `AIza` key from AI Studio so it does not expire
mid-review.

---

## 2. Create app

| Question | Answer |
|---|---|
| App name | DuSu |
| Default language | English (India) – en-IN |
| App or game | **App** |
| Free or paid | **Free** (cannot be changed to paid later) |
| Declarations — Developer Program Policies | ✅ Accept |
| Declarations — US export laws | ✅ Accept |

---

## 3. Store listing

### Short description (≤80 chars) — copy exactly

```
Practice spoken English daily with an AI coach that remembers you.
```

### Full description (≤4000 chars) — copy exactly

```
Most of us know English. We just freeze when it's time to speak it.

DuSu is a voice-first English speaking coach. You talk out loud, DuSu listens, and DuSu talks back — like a patient friend who never judges you, never laughs, and never makes you feel small for making a mistake.

No grammar drills. No flashcards. No boring lessons. Just real speaking practice, out loud, every day.

WHAT YOU CAN DO

• Talk — free, warm English conversation that never ends. Talk about your day, your work, your dreams. DuSu follows your interests.

• Interview Prep — a realistic mock HR interview that adapts to your answers, then gives you a full scorecard: grammar, fluency, confidence, communication, vocabulary and professionalism, plus your filler words and a rewritten "better answer".

• Daily Talk — start in Hindi, and DuSu shows you how to say the same thing in natural English. Perfect when English still feels heavy.

• Learn — say anything in Hindi or Hinglish and instantly hear the natural spoken English version.

A COACH THAT ACTUALLY REMEMBERS YOU

DuSu remembers your name, your goal, what you did yesterday, and what you said you were worried about. Come back tomorrow and the conversation continues where it stopped — it is one ongoing relationship, not a fresh chatbot every time.

BUILT FOR REAL PROGRESS

• A 7-level journey from "Thinking in English" to "Fluency"
• A level check that finds your real starting point
• XP, streaks, badges and a leaderboard to keep you showing up
• A weekly personal note from DuSu about how far you've come

MADE FOR INDIA

Built for freshers, students and working professionals preparing for job interviews, campus placements, and everyday confidence. Hindi-friendly throughout — start where you are, not where a textbook thinks you should be.

WHAT YOU NEED

• An internet connection
• A device with a microphone
• Chrome (DuSu uses your browser's built-in speech, so nothing is recorded or uploaded by us)

Speak with Confidence.
```

### Graphics you must upload

| Asset | Spec | Status |
|---|---|---|
| App icon | 512×512 PNG, 32-bit | ✅ `android-twa\play-icon-512.png` |
| Feature graphic | 1024×500 PNG/JPG, **no transparency** | ✅ `android-twa\play-feature-1024x500.png` (regenerate with `gen_feature_graphic.py`) |
| Phone screenshots | 2–8 required, 16:9 or 9:16, 320–3840px | ❌ take from your phone |

Screenshot suggestions (take these 5 on your phone): Home with "Start Speaking", a live Talk session, the Interview scorecard, the Journey/roadmap screen, the Leaderboard.

### Store settings

| Question | Answer |
|---|---|
| App category | **Education** |
| Tags | Language learning, Education |
| Email address | support.ruralrootcloud@gmail.com |
| Website | https://dusu.ruralrootcloud.com |
| Phone | optional — leave blank |
| External marketing | No (unless you want it) |

---

## 4. App content → Privacy policy

| Question | Answer |
|---|---|
| Privacy policy URL | `https://dusu.ruralrootcloud.com/privacy` |

---

## 5. App content → App access

Select: **All or some functionality is restricted**

Add an instruction entry:

| Field | Value |
|---|---|
| Name | Google Sign-In required |
| Username | *(your demo Google account email — see §1b)* |
| Password | *(that account's password)* |
| Any other instructions | `DuSu requires Google Sign-In. Tap the Google button on the launch screen and sign in with the account above. This account is pre-approved on our free-access list, so no API keys are needed. After sign-in you may be asked to complete a short spoken level test — tap Skip to reach the home screen, then tap "Start Speaking" to try the main feature. A microphone permission prompt will appear; please allow it.` |

---

## 6. App content → Ads

| Question | Answer |
|---|---|
| Does your app contain ads? | **No** |

Verified: no AdMob, no ad SDK anywhere in the codebase.

---

## 7. App content → Content rating (IARC questionnaire)

| Question | Answer |
|---|---|
| Email address | support.ruralrootcloud@gmail.com |
| Category | **Reference, News, or Educational** |
| Violence | No |
| Sexuality / nudity | No |
| Profanity or crude humor | No |
| Controlled substances (drugs, alcohol, tobacco) | No |
| Gambling / simulated gambling | No |
| Horror / fear themes | No |
| Does the app let users interact or communicate with each other? | **No** — users talk only to the AI, never to other users |
| Does the app share user-provided personal information with third parties? | **No** — the leaderboard shows only auto-generated aliases (e.g. "BraveCheetah"), never real names |
| Does the app share the user's current physical location? | **No** — no location permission is requested |
| Can users purchase digital goods? | **No** |
| Does the app contain AI-generated content? | **Yes** |
| Is there a way for users to report AI-generated content? | **Yes** — Help & Feedback → "Report an inappropriate response" |
| Is there an unmoderated / user-generated content feed? | No |

> If asked about generative AI safeguards: DuSu relies on the underlying model providers' safety filtering (Google Gemini, Groq, OpenRouter), plus warm-coach system prompts and in-app reporting. There is no separate moderation layer.

---

## 8. App content → Target audience and content

| Question | Answer |
|---|---|
| Target age groups | **18 and over** |
| Appeals to children? | **No** |
| Designed for Families programme | **No — do not opt in** |

Why 18+: DuSu's positioning is job interviews and campus placements, and the privacy policy already states it is not directed at under-13s. Selecting any under-18 bracket pulls you into a far stricter Families policy tier with extra requirements — avoid it unless you genuinely want teen users.

---

## 9. App content → Data safety (the long one)

### Overview answers

| Question | Answer |
|---|---|
| Does your app collect or share any of the required user data types? | **Yes** |
| Is all of the user data collected by your app encrypted in transit? | **Yes** (HTTPS / WSS) |
| Do you provide a way for users to request that their data be deleted? | **Yes** |
| Data deletion URL | `https://dusu.ruralrootcloud.com/account-deletion` |

### Data types — declare exactly these

| Data type | Collected | Shared | Purpose | Required? |
|---|---|---|---|---|
| **Personal info → Name** | Yes | **Yes** — sent to AI providers as conversation context | App functionality, Personalization | Required |
| **Personal info → Email address** | Yes | No | Account management | Required |
| **Personal info → User IDs** | Yes (Google account ID) | No | Account management | Required |
| **Photos and videos → Photos** | Yes (Google profile picture) | No | App functionality (avatar) | Required |
| **App activity → Other user-generated content** | Yes (spoken practice text, conversation memory) | **Yes** — sent to AI providers to generate replies | App functionality | Required |
| **App activity → App interactions** | Yes (XP, streaks, levels, session counts) | No | App functionality, Personalization | Required |
| **Personal info → Other info** | Yes (optional AI provider API keys the user adds) | No | App functionality | **Optional** |

### Notes for the "shared" entries

When Play asks *why* data is shared, the honest answer is: conversation text and the user's name are transmitted to third-party AI model providers (Google Gemini, Groq, OpenRouter) solely to generate the assistant's reply. It is a pass-through for app functionality — not sold, not used for advertising, and not used to train models.

### What to say NO to

Location, Financial info, Health, Contacts, Calendar, SMS/Call logs, Files/Docs, Device/other IDs for advertising, Audio files. Confirmed in code: the app requests only `INTERNET`, `ACCESS_NETWORK_STATE`, `POST_NOTIFICATIONS`, `RECEIVE_BOOT_COMPLETED`. No microphone permission is declared by the app itself — speech is handled by Chrome.

### ⚠️ One accuracy caveat to review before you sign this

**Resolved.** `privacy.html` previously claimed speech-to-text happens "entirely in your own browser and are never uploaded anywhere." On Android, Chrome's Web Speech API **streams audio to Google's speech servers** for recognition — it is not on-device, so that wording overstated the case. It now has a dedicated "How speech is handled" section stating plainly that DuSu never receives your audio, while disclosing that your browser vendor may process it under their own policy.

This matters for the form above: you are declaring that DuSu does **not** collect audio, which is true — the app has no microphone permission and the server only ever receives text. Do not tick any audio data type.

---

## 10. App content → remaining declarations

| Section | Answer |
|---|---|
| Government apps | No |
| Financial features | **None of these** |
| Health apps | No |
| News app | No |
| COVID-19 contact tracing/status | No |
| Data safety — Play Families policy | N/A (18+) |

---

## 11. Closed testing (required before production)

New personal developer accounts must run a closed test with **12+ testers opted in continuously for 14 days** before production access unlocks. You said you have your 12.

1. **Test and release → Testing → Closed testing → Create track** (name: `closed-1`)
2. **Testers tab** → add the 12 email addresses (or create a Google Group and link it)
3. Copy the **opt-in URL** and send it to all 12 — each must open it and tap **Become a tester**. They must *stay* opted in for the full 14 days; anyone who drops out resets your count.
4. **Create release** → upload `app-release.aab`
5. Release name: `1.0 (1)` · Release notes:
   ```
   First release of DuSu — voice-first English speaking practice with an AI coach.
   ```
6. **Save → Review release → Start rollout to Closed testing**

> Tell your testers to actually *use* the app during the 14 days, not just install it. Google looks at real testing activity, and a dead cohort is a common reason the production unlock gets refused.

---

## 12. Production release

Only after 14 days of closed testing:

1. **Test and release → Production → Create release**
2. Promote the same AAB (or upload a new one — bump `versionCode` to `2` in `android-twa/app/build.gradle.kts` if you rebuild)
3. Fill release notes → **Review release** → **Start rollout to Production**
4. First review typically takes a few hours to ~7 days

---

## 13. After the app goes live — don't forget

- [ ] Add the **Play App Signing SHA-256** to `ANDROID_CERT_SHA256` (§1a) — otherwise Play users see the browser URL bar
- [ ] Install from Play on a real phone and confirm it opens full-screen, mic works, and sign-in works
- [ ] Add `https://dusu.ruralrootcloud.com` to Google Cloud Console → OAuth client → Authorized JavaScript origins, if not already done — sign-in breaks without it
- [ ] Remove the demo account from `UNLIMITED_EMAILS` once review is done (or keep it — each update gets reviewed too)
- [ ] Revisit `access_phase` if you flipped it to `quota` for review

---

## 14. Readiness check — status as of 2026-09-21

**Not ready to submit.** Four items outstanding:

| # | Blocker | Owner |
|---|---|---|
| 1 | **Reviewer access** — see §1b. Still unresolved; the highest rejection risk on this list. | You (decision) + code change |
| 2 | **Phone screenshots** (2 minimum) | You — needs your device |
| 3 | **12 testers not invited** — the 14-day closed-testing clock has not started | You |
| 4 | **Server LLM keys** — Groq revoked, Gemini running on an expiring `AQ.` OAuth token. Only matters for accounts on the default chain (owner + any exempted reviewer), not for testers on their own keys. | You — new keys |

**Ready:** signed AAB (still current — no `android-twa/app/src` changes since it was
built), feature graphic, app icon, privacy/terms/account-deletion pages with the
support email, asset links verified against Google's Digital Asset Links API, and the
full answer sheet in §2–§10 of this file.

**Unverified:** the bottom-nav fix (nav visibility is now derived from the visible
screen rather than set by `show()`). Deployed but only confirmable on a real device —
retest sign-in → sign-out → sign-in as a second account before submitting.

---

## 15. Known gaps

- No payment/subscription code exists — `/subscribe` is a placeholder. If you sell subscriptions later, it **must** go through Google Play Billing, not Razorpay/Stripe, or you violate Play's Payments policy.
- Free-tier LLM models can occasionally produce garbled output — an accepted quality ceiling of the $0 provider chain, not a bug introduced by the launch work.
- `is_office()` still *reads* like "free access" but *means* "must BYOK". The admin UI label is fixed; the function name is not. See the warning in §1b.
- GitHub Models has been removed from the keys screen — it is in a platform-wide retirement brownout (410 for everyone), so no user could ever have made it work. Three providers remain: Groq, Gemini, OpenRouter; any 2 satisfy the minimum.
- Every request through the shared cloudflared tunnel costs ~1s (app answers in ~3ms locally). Affects RootEd identically, so it is shared infrastructure, not DuSu. Deferred to the team.
- **Super-admin portal** is live at `/superadmin` with its own credentials, separate from Google sign-in, gated by `SUPERADMIN_USER` / `SUPERADMIN_PASS`. Returns 503 when unset. Note its API field is `username`, not `user`.

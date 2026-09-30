# DuSu — Domain Cutover to `dusu.ranabrothers.online`

> **Question asked:** can the URL move to the Rana Brothers domain without affecting the
> other things on this box, and without affecting the product?
>
> **Answer: yes — because we ADD the new hostname instead of MOVING to it.** Both hostnames
> serve the same container, the same database and the same accounts, in parallel, for as long
> as you want. There is no moment where the app is down and no moment where the old URL stops
> working. The one unavoidable effect is described in §4 and it costs a user one click.

---

## 1. What is actually involved

DuSu's frontend is already **origin-agnostic**: the client builds its WebSocket URL from
`location.host` (`WS_URL` in `test_client.html`) and every API call is a root-relative path.
The service worker and the PWA manifest are relative too. So the *app* does not care what
hostname it is served from — it works on both the moment DNS points at it.

That leaves exactly five things that name the host, and only two of them are outside this repo.

| # | Thing | Where | Who does it |
|---|---|---|---|
| 1 | Tunnel public hostname + DNS | Cloudflare Zero Trust dashboard | **You** (§3, step 1) |
| 2 | Google OAuth authorised origin | Google Cloud Console | **You** (§3, step 2) |
| 3 | OpenRouter `HTTP-Referer` attribution header | `backend/app/config.py` | Done (§2) |
| 4 | TWA `launchUrl` / `hostName` / `asset_statements` | `android-twa/.../strings.xml` | Done (§2) |
| 5 | Docs, Play guide, install guide | various `.md` | Done (§2) |

`/.well-known/assetlinks.json` needs **no** change: `main.py` builds it from the
`ANDROID_CERT_SHA256` / `ANDROID_TWA_PACKAGE` env vars, so it serves the correct statement on
whatever hostname the backend answers on. Already verified working on the current host.

---

## 2. What is protected, and why

### The "other side" — nothing on it is touched

This box runs three separate Cloudflare tunnels. The cutover only **adds one public hostname
to the tunnel DuSu already uses**. Nothing is edited, restarted, or re-pointed.

| Also on this box | Status after cutover |
|---|---|
| `rooted-prod` tunnel (`~/.cloudflared/rooted-prod-config.yml`) — RootEd prod, UAT, storage, and the `*.ruralrootcloud.com` wildcard → `localhost:80` | **Untouched.** Different tunnel, config-file based, not opened. |
| `cloudflared-ssh.service` — `ssh.ruralrootcloud.com` | **Untouched.** Different tunnel. |
| `cloudflared.service` — the token/dashboard-managed tunnel DuSu uses | Gains one extra public hostname. Existing routes unchanged; no restart needed (remotely-managed tunnels pick up route changes live). |
| `ranabrothers.online` apex — currently 308-redirects to `/edgeverify/` | **Untouched.** We add the `dusu` subdomain only; apex rules and any other record on that zone are not modified. |
| `dusu.ruralrootcloud.com` | **Stays live.** Not deleted, not redirected. |

### The product — nothing breaks

| Concern | Reality |
|---|---|
| Downtime | None. The new hostname starts answering the moment the route exists; the old one never stops. |
| Sign-in | Google OAuth lists **both** origins (you add the new one, you do not remove the old one), so sign-in works on either. |
| User data | Everything is keyed on the Google `sub` in Postgres — profile, progress, memory, conversations, BYOK keys. It is the same database on both hostnames. Nothing to migrate. |
| Stored AI keys | `POST /keys/get` returns the signed-in user's own stored keys, and the client calls it on load — so keys reappear on the new origin automatically after sign-in. No re-entry. |
| Installed Android app | **No installed users to break — DuSu is not on Play yet.** This is the cheapest possible moment to move; see §5. |
| PWA installs | Per-origin. An existing install keeps pointing at the old host and keeps working. |
| Service worker cache | Per-origin, so the new origin starts with a clean cache. No stale-shell risk. |
| Rollback | Delete the new public hostname. Everything is already working on the old one. |

---

## 3. ⚠️ The unavoidable effect: one sign-in

`localStorage` is scoped per origin. A user who has been using `dusu.ruralrootcloud.com` and
then opens `dusu.ranabrothers.online` arrives **signed out** — the new origin has no
`dusu_token`.

What that costs them: **one tap on "Sign in with Google."** After that:

- profile, XP, streak, badges, memory, conversation history — all restored from the server,
- BYOK keys — restored from the server via `/keys/get`,
- level-test status — restored (`onboarded` comes from `/me`).

What is genuinely lost (all of it trivial, all of it per-device UI state): the cached
`dusu_state` first-paint snapshot, the `dusu_daily_resume` tail of the last Daily Talk, the
`dusu_usage` local counter, the `dusu_think` timing samples, and the cached weekly letter.

This is inherent to changing origin — no configuration avoids it. It is also why the old
hostname stays alive: nobody is forced through it until they choose the new link.

---

## 4. Do these two steps (≈5 minutes, dashboards only)

Both are additive. Neither removes anything.

### Prerequisite

`ranabrothers.online` must be in the **same Cloudflare account** as the tunnel behind this
box's `cloudflared.service`. Both zones already resolve to Cloudflare, but same-account is not
provable from the host — the dashboard will simply not offer the domain in step 1's dropdown
if it is in a different account. If it isn't offered, move the zone to that account (or use a
Cloudflare API token from the account that owns the tunnel) and retry.

### Step 1 — add the public hostname (Cloudflare Zero Trust)

1. Cloudflare Zero Trust → **Networks → Tunnels** → open the tunnel behind this host's
   `cloudflared` systemd service (the token-based one — the same tunnel that already serves
   `dusu.ruralrootcloud.com`; **not** `rooted-prod`, **not** the SSH tunnel).
2. **Public Hostname** tab → **Add a public hostname**:
   - Subdomain: `dusu`
   - Domain: `ranabrothers.online`
   - Path: *(leave empty)*
   - Service: `HTTP` → `localhost:3878`
3. Save. This creates the DNS record too. **Do not touch or delete the existing
   `dusu.ruralrootcloud.com` hostname.**

WebSocket upgrade for `/ws/interview` passes through automatically, same as it already does.

### Step 2 — authorise the new origin for Google Sign-In

Google Cloud Console → **APIs & Services → Credentials** → the OAuth 2.0 Client ID used by
`GOOGLE_CLIENT_ID` → **Authorised JavaScript origins** → **Add**:

```
https://dusu.ranabrothers.online
```

**Keep `https://dusu.ruralrootcloud.com` in the list.** Removing it signs out the old host.
Changes can take a few minutes to propagate.

### Step 3 — verify

```bash
# resolves and reaches the backend
curl -s https://dusu.ranabrothers.online/health

# the app itself
curl -s -o /dev/null -w '%{http_code}\n' https://dusu.ranabrothers.online/

# Digital Asset Links (needed later for the TWA) — must list com.dusu.app
curl -s https://dusu.ranabrothers.online/.well-known/assetlinks.json

# the OLD host must still work — this is the "no impact" check
curl -s https://dusu.ruralrootcloud.com/health
```

Then open `https://dusu.ranabrothers.online` in a browser and sign in once. If sign-in fails
with `origin_mismatch`, step 2 hasn't propagated yet — wait and retry.

---

## 5. Then: Play submission uses the new URL from day one

DuSu is **not yet on Play** (`PLAYSTORE_SUBMISSION_GUIDE.md` still has closed testing ahead).
That is what makes this cheap: there are no installed users whose app is pinned to the old
hostname, so the TWA can be repointed with zero blast radius.

Already done in the repo:

- `launchUrl` and `hostName` → `dusu.ranabrothers.online`
- `asset_statements` lists **both** origins, so the app verifies on either — which keeps the
  already-built `DuSu-app.apk` and any sideloaded copy working while you transition.

Still to do, in this order:

1. Finish §4 and confirm `https://dusu.ranabrothers.online/.well-known/assetlinks.json`
   returns the `com.dusu.app` statement.
2. Rebuild: `cd android-twa && ./gradlew bundleRelease` (`JAVA_HOME` must be a real JDK 17,
   not the Android Studio JBR).
3. Submit with the new URLs — the Play guide's Website / Privacy / Terms / Deletion fields
   have already been updated to the new host.

---

## 6. Retiring the old hostname (optional, much later)

Not part of this change, and not urgent — the old hostname costs nothing to keep. When you do
want it gone:

1. Wait until Play has been live on the new URL for **30+ days** and old-host traffic is
   negligible (`journalctl -u cloudflared` on this box).
2. Replace the Cloudflare public hostname for `dusu.ruralrootcloud.com` with a **301 redirect
   rule** to `https://dusu.ranabrothers.online` rather than deleting it outright — a redirect
   keeps old links, old QR codes and old screenshots working.
3. Remove `https://dusu.ruralrootcloud.com` from the Google OAuth origins **last**, and only
   once the redirect is in place.
4. Drop the legacy entry from `asset_statements` at the next app release.

Never do any of this mid-Play-review.

---

## 7. Rollback

If anything looks wrong after §4, the entire change is one deletion: remove the
`dusu.ranabrothers.online` public hostname in the Cloudflare tunnel. The old hostname was
never modified, so the product is instantly back to exactly its previous state. The repo
changes in §2 are inert without that route — the only live-behaviour item among them is the
OpenRouter `HTTP-Referer` attribution header, which is cosmetic and affects nothing if the
hostname doesn't resolve yet.

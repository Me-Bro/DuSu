/* DuSu service worker — makes the app installable + caches the shell.
   Network-first for navigations (always try fresh HTML so deploys show up),
   falling back to cache when offline. WebSocket + API calls are never cached. */

const CACHE = "dusu-v37";   // bumped: a limit (free daily limit, trial over, free sessions used up, an unnamed key limit) is now the bottom pop-up with a "Free version / Free keys" note and a plan card, never the small top banner (v36: the key-problem pop-up and the Keys screen redrawn - an icon, one plain sentence with when it is back, a card per key with a coloured status and a Replace button (v35: a locked screen no longer kills Face-to-Face / Interview / a practice conversation / the Home chat either - they pause, and reconnect quietly if the connection dropped (v34: the same for Daily Talk / Learn (the mic and Reply come back) (v33: real install icons + manifest id (the web-app install button), the key screens, notification fixes - the push is shown FIRST and the "arrived" receipt follows, a nudge while the app is open is silent + an in-app notice, a monochrome badge (v32: Notifications (flag-gated, ships dark: personal practice / streak / weekly-note nudges as push, an "arrived" receipt and a tap beacon) (v31: Grammar Coach (flag-gated, ships dark: every English sentence checked, corrected and explained, in its own section) (v30: My Day check / uncheck on tasks, habits, goals and reminders - a finished item stays where it was checked and one tap puts it back (v29: My Day repeating reminders - set once, they ring on chosen weekdays until paused or deleted (v28: Job Interview Practice (renamed from Resume Interview) with detailed saved reports, improvement plan and progress since the last interview (v27: Resume Interview (flag-gated, ships dark) (v26: My Day lists show everything with visible edit/delete/add, first-use crash fixed (v25: My Day reminders in Today + their own tab, edit/delete, DuSu reads them all (v24: dashboard early-access list; v23: My Day; v22: language scope (old features pinned) + Home feature icons; v21: Home 2.0; v19: "DuSu knows your progress" switch, v18: Practice Room)
const SHELL = ["/", "/logo.png", "/manifest.webmanifest"];
// Cache-first is now an ALLOWLIST, not a denylist — every new authenticated GET
// endpoint added to main.py is safe by default instead of needing a matching
// entry here (the old denylist silently went stale as endpoints were added:
// /leaderboard, /league, /missions, /season-awards, /confidence-check all fell
// through to cache-first and either leaked one user's data to the next user on
// a shared device, or froze permanently for the life of the cached entry).
const CACHEABLE_PREFIXES = ["/logo.png", "/manifest.webmanifest", "/assets/"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).catch(() => {}));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;                       // never cache POST/auth
  const url = new URL(req.url);

  // Navigations: network-first so a new deploy is picked up immediately. Only
  // store the response as the offline "/" shell if it's actually the HTML app —
  // an unauthenticated 401 JSON hit on a client route that shadows a real API
  // path (e.g. /leaderboard with no token) must NOT permanently replace the
  // cached shell with an error body.
  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req).then((res) => {
        if (res.ok && (res.headers.get("content-type") || "").includes("text/html")) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put("/", copy)).catch(() => {});
        }
        return res;
      }).catch(() => caches.match("/"))
    );
    return;
  }

  // Everything else that isn't a known static asset goes straight to the
  // network, no cache read or write — this is live/per-user data by default.
  if (!CACHEABLE_PREFIXES.some((p) => url.pathname.startsWith(p))) return;

  // Static assets: cache-first, then network (and store).
  event.respondWith(
    caches.match(req).then((hit) =>
      hit || fetch(req).then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
        return res;
      }).catch(() => hit)
    )
  );
});

/* ---------- Web Push: My Day reminders and Notifications nudges ----------
   The server sends an encrypted message. A My Day reminder carries single-purpose, signed, 24-hour tokens (`data.act`) so the notification's buttons (Done / Later /
   Skip) can act with NO login - a service worker cannot read the app's session; if a DuSu window is visible the in-app reminder card already shows it, so no second
   alert is raised. A Notifications NUDGE (`data.nid`) is different on purpose:
     * it is ALWAYS shown, and shown FIRST - a push that raises no notification can get the subscription revoked (iPhone insists on it; Chrome puts up a generic
       "this site has been updated" one), and the "it arrived" receipt used to be awaited BEFORE showing, so a slow network delayed or lost the notification itself;
     * the receipt (a signed single-purpose token) follows in the background, even if showing failed - the push DID arrive;
     * while a DuSu window is visible the notification is `silent` and the window is told, so it draws an in-app notice instead of buzzing twice.
   Push is opt-in and best-effort; the in-app card is the guaranteed channel. */
const ICON = "/assets/icons/dusu-192-v1.png";
const BADGE = "/assets/icons/badge-96-v1.png";          // white-on-transparent: Android draws only its alpha in the status bar (the 1.7 MB colour logo became a white square)

self.addEventListener("push", (event) => {
  let d = {};
  try { d = event.data ? event.data.json() : {}; } catch (_) {}
  event.waitUntil((async () => {
    const wins = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    const visible = wins.some((w) => w.visibilityState === "visible");
    const nt = d.data && d.data.nid;                                       // a Notifications nudge (backend/app/notify), not a My Day reminder
    if (nt) {
      if (visible) wins.filter((w) => w.visibilityState === "visible").forEach((w) => { try { w.postMessage({ type: "nt-nudge", id: d.data.nid, title: d.title || "DuSu", body: d.body || "", url: d.data.url || "/" }); } catch (_) {} });
      try {
        await self.registration.showNotification(d.title || "DuSu", {
          body: d.body || "", tag: d.tag || "dusu-nudge", data: d.data || {}, actions: (d.actions || []).slice(0, 3), icon: ICON, badge: BADGE, silent: visible,
        });
      } catch (_) {}
      if (d.data.ack) {                                                    // tell the server it ARRIVED (signed single-purpose token, no login needed)
        try { await fetch("/notify/ack", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ t: d.data.ack }), keepalive: true }); } catch (_) {}
      }
      return;
    }
    wins.forEach((w) => { try { w.postMessage({ type: "pl-due" }); } catch (_) {} });
    if (visible) return;
    await self.registration.showNotification(d.title || "DuSu", {
      body: d.body || "", tag: d.tag || "dusu-reminder", data: d.data || {}, actions: (d.actions || []).slice(0, 3),
      icon: ICON, badge: BADGE,
    });
  })());
});

self.addEventListener("notificationclick", (event) => {
  const n = event.notification, data = n.data || {}, action = event.action;
  n.close();
  event.waitUntil((async () => {
    const wins = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    if (data.nid) {                                                         // a Notifications nudge: open Home and report the tap
      const u = data.url || "/";
      for (const w of wins) {
        if ("focus" in w) { await w.focus(); try { w.postMessage({ type: "nt-open", id: data.nid }); } catch (_) {} return; }
      }
      if (self.clients.openWindow) await self.clients.openWindow(u + (u.indexOf("?") < 0 ? "?" : "&") + "n=" + encodeURIComponent(data.nid));
      return;
    }
    if (action && data.act && data.act[action]) {                         // a button: do exactly that one thing
      try {
        await fetch("/planner/r/act", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ t: data.act[action] }) });
      } catch (_) {}
      wins.forEach((w) => { try { w.postMessage({ type: "pl-due" }); } catch (_) {} });
      return;
    }
    const url = data.url || "/my-day";                                    // the body: open My Day
    for (const w of wins) {
      if ("focus" in w) { await w.focus(); try { w.postMessage({ type: "pl-open", url }); } catch (_) {} return; }
    }
    if (self.clients.openWindow) await self.clients.openWindow(url);
  })());
});

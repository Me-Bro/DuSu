/* DuSu service worker — makes the app installable + caches the shell.
   Network-first for navigations (always try fresh HTML so deploys show up),
   falling back to cache when offline. WebSocket + API calls are never cached. */

const CACHE = "dusu-v23";   // bumped: My Day (v22: language scope (old features pinned) + Home feature icons; v21: Home 2.0; v19: "DuSu knows your progress" switch, v18: Practice Room)
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

/* ---------- My Day reminders (Web Push) ----------
   The server sends an encrypted message; `data.act` carries single-purpose, signed, 24-hour tokens so the notification's buttons (Done / Later /
   Skip) can act with NO login - a service worker cannot read the app's session. If a DuSu window is visible the in-app reminder card already shows
   it, so no second alert is raised: the window is just told to refresh. Push is opt-in and best-effort; the in-app card is the guaranteed channel. */
self.addEventListener("push", (event) => {
  let d = {};
  try { d = event.data ? event.data.json() : {}; } catch (_) {}
  event.waitUntil((async () => {
    const wins = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    wins.forEach((w) => { try { w.postMessage({ type: "pl-due" }); } catch (_) {} });
    if (wins.some((w) => w.visibilityState === "visible")) return;
    await self.registration.showNotification(d.title || "DuSu", {
      body: d.body || "", tag: d.tag || "dusu-reminder", data: d.data || {}, actions: (d.actions || []).slice(0, 3),
      icon: "/logo.png", badge: "/logo.png",
    });
  })());
});

self.addEventListener("notificationclick", (event) => {
  const n = event.notification, data = n.data || {}, action = event.action;
  n.close();
  event.waitUntil((async () => {
    const wins = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
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

/* DuSu service worker — makes the app installable + caches the shell.
   Network-first for navigations (always try fresh HTML so deploys show up),
   falling back to cache when offline. WebSocket + API calls are never cached. */

const CACHE = "dusu-v13";   // bumped: post-login key gate + self-hosted DB cutover
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

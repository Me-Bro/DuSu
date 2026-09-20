# DuSu — Cloudflare Tunnel (dusu.ruralrootcloud.com)

DuSu is exposed at `https://dusu.ruralrootcloud.com` through **this box's existing
host-level cloudflared** — the same way `rooted-prod` (RootEd) and the SSH tunnel
already run here. There is **no cloudflared container in `docker-compose.yml`**; the
tunnel is infrastructure that lives outside this repo, on the host.

```
users → https://dusu.ruralrootcloud.com
              │
              ▼
      cloudflared (systemd service "cloudflared", already running,
                    token-based / remotely-managed — routes configured
                    in the Cloudflare Zero Trust dashboard, not a local file)
              │
              ▼
      http://localhost:${BACKEND_PORT:-3878}   (DuSu's backend container,
                                                  published by docker-compose.yml)
```

This tunnel is **separate from `rooted-prod`** (which stays config-file based via
`~/.cloudflared/rooted-prod-config.yml` and must not be touched for DuSu) — it was
already running on this host with no routes configured, so DuSu reuses it instead of
adding a third tunnel/systemd unit.

## 1. Add the Public Hostname route (one-time, in the Cloudflare dashboard)

This tunnel is token-based, so its routes live in Cloudflare's dashboard, not in a
local `config.yml`:

1. Cloudflare Zero Trust dashboard → **Networks → Tunnels** → open the tunnel behind
   this host's `cloudflared` systemd service.
2. **Public Hostname** tab → **Add a public hostname**:
   - Subdomain: `dusu`
   - Domain: `ruralrootcloud.com`
   - Service: `HTTP` → `localhost:3878` (or whatever `BACKEND_PORT` is set to — see
     root `.env.example`)

   This also creates the DNS record for `dusu.ruralrootcloud.com` — no manual DNS
   step needed. WebSocket upgrade (`/ws/interview`) passes through automatically.

No systemd/service changes needed on the host — `cloudflared.service` is already
running; it just picks up the new route.

## 2. Configure the repo

`backend/.env` needs the usual LLM keys + `SESSION_SECRET`. Leave `DATABASE_URL`
empty: the database is this stack's own `db` service, and `docker compose` builds the
URL from the `POSTGRES_*` vars in the root `.env` and injects it (overriding
`backend/.env`). `GOOGLE_CLIENT_ID`'s OAuth client must list
`https://dusu.ruralrootcloud.com` under **Authorized JavaScript origins**
(Google Cloud Console → Credentials) or sign-in will fail on this hostname.

## 3. Run it

```bash
docker compose up -d --build
```

That is the PRODUCTION run: the code is baked into the image, no hot reload. For a
dev loop that mounts your working tree instead, add the dev overlay:
`docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d`.

This starts both containers — `db` (Postgres, not published to the host) and `backend`
(published on `localhost:${BACKEND_PORT:-3878}`). The backend waits for the database's
healthcheck before booting. The tunnel itself is already running on the host from
step 1.

Verify:

```bash
curl -s http://localhost:3878/health        # backend directly
curl -s https://dusu.ruralrootcloud.com/health   # through the tunnel, once step 1 is done
```

Logs: `docker compose logs -f backend` (app) and `journalctl -u cloudflared -f`
(host tunnel, shared across all hostnames it routes — filter by eye for DuSu traffic).

## Notes

- If `BACKEND_PORT` is ever changed, update the Public Hostname route's target port to
  match (dashboard, step 1) — the two aren't linked automatically.
- Cost: cloudflared already runs on this host for other projects, so DuSu adds $0
  beyond the `ruralrootcloud.com` domain itself.

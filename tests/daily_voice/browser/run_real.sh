#!/usr/bin/env bash
# Daily Talk / Learn vs a locked screen - the browser tier against the REAL app: uvicorn + a SCRATCH Postgres (the keys harness's tests/keys/e2e_server.py: the real key engine,
# scripted fake providers), a real Chromium in the Playwright image behind a WebSocket proxy. Everything is removed afterwards; no host port is bound; the network is INTERNAL
# (no route out); never the app's own database.
#   tests/daily_voice/browser/run_real.sh [lock.spec.cjs]
# Needs the Playwright modules once (see tests/notify/README.md) and the test image `dusu-ri-test`.
# DV_BACKEND=<path> runs against a COPY of backend/ (mutants.sh / the "does it fail on the old code" run); DV_BACKEND=baked runs the code INSIDE the image (DV_TEST_IMAGE=dusu-backend:latest).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
IMG="${DV_TEST_IMAGE:-dusu-ri-test}"
BACKEND="${DV_BACKEND:-$REPO/backend}"
MOUNT=(-v "$BACKEND":/app); [ "$BACKEND" = baked ] && MOUNT=()
PW="${PW_MODULES:-$HOME/.cache/dusu-ri-pwrun/node_modules}"
OUT="${OUT_DIR:-$HOME/.cache/dusu-dv-shots}"
SPEC="${1:-lock.spec.cjs}"
mkdir -p "$OUT"
NET="dv-e2e-net-$$"; PG="dv-e2e-pg-$$"; SRV="dv-e2e-srv-$$"
cleanup() { docker rm -f "$SRV" "$PG" >/dev/null 2>&1 || true; docker network rm "$NET" >/dev/null 2>&1 || true; }
trap cleanup EXIT
docker network create --internal "$NET" >/dev/null
docker run -d --name "$PG" --network "$NET" -e POSTGRES_USER=ky -e POSTGRES_PASSWORD=ky -e POSTGRES_DB=ky postgres:18-alpine >/dev/null
for _ in $(seq 1 60); do docker exec "$PG" pg_isready -U ky -d ky >/dev/null 2>&1 && break; sleep 1; done
sleep 2
rm -rf "$REPO/tests/keys/.e2e"
# provider keys blanked: the bind-mounted backend/ holds the real .env
docker run -d --name "$SRV" --network "$NET" \
  -e DATABASE_URL="postgresql://ky:ky@$PG:5432/ky" -e DATABASE_SSL=false -e SESSION_SECRET=ky-e2e-secret -e GOOGLE_CLIENT_ID=e2e-client \
  -e GROQ_API_KEY= -e GEMINI_API_KEY= -e OPENROUTER_API_KEY= -e GITHUB_TOKEN= \
  "${MOUNT[@]}" -v "$REPO/tests":/tests "$IMG" python /tests/keys/e2e_server.py >/dev/null
for _ in $(seq 1 90); do
  docker exec "$SRV" python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=2)" >/dev/null 2>&1 && break
  sleep 1
done
docker exec "$SRV" python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=2)" >/dev/null 2>&1 || { echo "the e2e server did not come up:"; docker logs "$SRV" 2>&1 | tail -30; exit 3; }
# --network container:... puts the browser in the SERVER's network namespace: the page is http://localhost:8000, a secure context (as production's https is)
docker run --rm --ipc=host --network "container:$SRV" --user "$(id -u):$(id -g)" -e HOME=/tmp -e NODE_PATH=/pw/node_modules -e OUT=/out -e REPO=/repo -e BASE="http://localhost:8000" \
  -e TOKENS=/repo/tests/keys/.e2e/tokens.json -e VERBOSE -e ONLY \
  -v "$REPO":/repo:ro -v "$PW":/pw/node_modules:ro -v "$OUT":/out -w /repo/tests/daily_voice/browser \
  mcr.microsoft.com/playwright:v1.60.0-noble node "$SPEC" || { rc=$?; echo "--- server log (tail) ---"; docker logs "$SRV" 2>&1 | tail -25; exit $rc; }
echo "--- server log (tail) - tracebacks / 5xx would show here ---"; docker logs "$SRV" 2>&1 | grep -E "Traceback|Error|500" | head -10 || true

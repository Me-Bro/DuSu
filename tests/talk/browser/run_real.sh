#!/usr/bin/env bash
# Talk - the browser tier against the REAL app: uvicorn + a SCRATCH MongoDB (a one-member replica set) on an INTERNAL docker network (tests/talk/browser/e2e_server.py: the real server code, the
# real topic bank, a scripted Talk model, scripted fake providers), a real Chromium in the Playwright image behind a WebSocket proxy. Everything is removed afterwards; no host port is
# bound; no key exists anywhere; never the app's own database.
#   tests/talk/browser/run_real.sh [real.spec.cjs]            ONLY=A1,B3 runs just those scenarios; SECTIONS=A,B the same by section letter
#   TK_BACKEND=<path>   run against a COPY of backend/ (mutants.py);  TK_BACKEND=baked  the code INSIDE the image (TK_TEST_IMAGE=dusu-backend:<tag>)
# Needs the Playwright modules once (see tests/notify/README.md) and the test image `dusu-mongo-test`.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
. "$REPO/tests/lib/scratch_mongo.sh"
IMG="${TK_TEST_IMAGE:-dusu-mongo-test}"
BACKEND="${TK_BACKEND:-$REPO/backend}"
MOUNT=(-v "$BACKEND":/app); [ "$BACKEND" = baked ] && MOUNT=()
PW="${PW_MODULES:-$HOME/.cache/dusu-ri-pwrun/node_modules}"
OUT="${OUT_DIR:-$HOME/.cache/dusu-tk-shots}"
SPEC="${1:-real.spec.cjs}"
mkdir -p "$OUT"
NET="tk-e2e-net-$$"; MG="tk-scratch-mongo-$$"; SRV="tk-e2e-srv-$$"
E2E=".e2e-$$"        # a directory per run: two runs side by side never delete each other's tokens
cleanup() { docker rm -f "$SRV" "$MG" >/dev/null 2>&1 || true; docker network rm "$NET" >/dev/null 2>&1 || true; rm -rf "$REPO/tests/talk/$E2E"; }
trap cleanup EXIT
docker network create --internal "$NET" >/dev/null
scratch_mongo_up "$NET" "$MG"
sleep 2
rm -rf "$REPO/tests/talk/$E2E"
# provider keys blanked: the bind-mounted backend/ holds the real .env
docker run -d --name "$SRV" --network "$NET" \
  -e E2E_DIR="/tests/talk/$E2E" -e MONGODB_URI="$(scratch_mongo_uri "$MG" tk)" -e DUSU_SCRATCH_ONLY=1 -e SESSION_SECRET=tk-e2e-secret -e GOOGLE_CLIENT_ID=e2e-client \
  -e GROQ_API_KEY= -e GEMINI_API_KEY= -e OPENROUTER_API_KEY= -e GITHUB_TOKEN= \
  "${MOUNT[@]}" -v "$REPO/tests":/tests "$IMG" python /tests/talk/browser/e2e_server.py >/dev/null
for _ in $(seq 1 90); do
  docker exec "$SRV" python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=2)" >/dev/null 2>&1 && break
  sleep 1
done
docker exec "$SRV" python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=2)" >/dev/null 2>&1 || { echo "the e2e server did not come up:"; docker logs "$SRV" 2>&1 | tail -30; exit 3; }
# --network container:... puts the browser in the SERVER's network namespace: the page is http://localhost:8000, a secure context (as production's https is)
docker run --rm --ipc=host --network "container:$SRV" --user "$(id -u):$(id -g)" -e HOME=/tmp -e NODE_PATH=/pw/node_modules -e OUT=/out -e REPO=/repo -e BASE="http://localhost:8000" \
  -e TOKENS="/repo/tests/talk/$E2E/tokens.json" -e VERBOSE -e ONLY -e SECTIONS \
  -v "$REPO":/repo:ro -v "$PW":/pw/node_modules:ro -v "$OUT":/out -w /repo/tests/talk/browser \
  mcr.microsoft.com/playwright:v1.60.0-noble node "$SPEC" || { rc=$?; echo "--- server log (tail) ---"; docker logs "$SRV" 2>&1 | tail -25; exit $rc; }
echo "--- server log (tail) - tracebacks / 5xx would show here ---"; docker logs "$SRV" 2>&1 | grep -E "Traceback|Error|500" | head -10 || true

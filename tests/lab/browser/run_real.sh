#!/usr/bin/env bash
# Grammar Lab - the browser tier against the REAL app: uvicorn + a SCRATCH MongoDB (a one-member replica set) (tests/lab/browser/e2e_server.py), a real Chromium in the Playwright image.
# Everything is removed afterwards; no host port is bound; never the app's own database.
#   tests/lab/browser/run_real.sh [real.spec.cjs]
# Needs the Playwright modules once (see ../../my_day/README.md) and the test image `dusu-mongo-test`.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
. "$REPO/tests/lib/scratch_mongo.sh"
IMG="${LAB_TEST_IMAGE:-dusu-mongo-test}"
BACKEND="${LAB_BACKEND:-$REPO/backend}"      # "baked" = test the code INSIDE the image (a built / deployed image)
MOUNT=(-v "$BACKEND":/app); [ "$BACKEND" = baked ] && MOUNT=()
PW="${PW_MODULES:-$HOME/.cache/dusu-ri-pwrun/node_modules}"
OUT="${OUT_DIR:-$HOME/.cache/dusu-lab-shots}"
SPEC="${1:-real.spec.cjs}"
mkdir -p "$OUT"
NET="lab-e2e-net-$$"; MG="lab-e2e-scratch-mongo-$$"; SRV="lab-e2e-srv-$$"
E2E=".e2e-$$"        # the tokens the server writes for the spec: a directory per run, so two runs side by side never delete each other's file
cleanup() { docker rm -f "$SRV" "$MG" >/dev/null 2>&1 || true; docker network rm "$NET" >/dev/null 2>&1 || true; rm -rf "$HERE/$E2E"; }
trap cleanup EXIT
docker network create "$NET" >/dev/null
scratch_mongo_up "$NET" "$MG"
sleep 2
rm -rf "$HERE/$E2E"
docker run -d --name "$SRV" --network "$NET" \
  -e E2E_DIR="/tests/lab/browser/$E2E" -e MONGODB_URI="$(scratch_mongo_uri "$MG" lab)" -e DUSU_SCRATCH_ONLY=1 -e SESSION_SECRET=lab-e2e-secret -e GOOGLE_CLIENT_ID=e2e-client \
  -e GROQ_API_KEY= -e GEMINI_API_KEY= -e OPENROUTER_API_KEY= -e GITHUB_TOKEN= \
  "${MOUNT[@]}" -v "$REPO/tests":/tests "$IMG" python /tests/lab/browser/e2e_server.py >/dev/null
for _ in $(seq 1 90); do
  docker exec "$SRV" python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=2)" >/dev/null 2>&1 && break
  sleep 1
done
docker exec "$SRV" python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=2)" >/dev/null 2>&1 || { echo "the e2e server did not come up:"; docker logs "$SRV" 2>&1 | tail -30; exit 3; }
docker run --rm --ipc=host --network "container:$SRV" --user "$(id -u):$(id -g)" -e HOME=/tmp -e NODE_PATH=/pw/node_modules -e OUT=/out -e REPO=/repo -e BASE="http://localhost:8000" \
  -e TOKENS="/repo/tests/lab/browser/$E2E/tokens.json" -e ORIG_HTML -e VERBOSE \
  ${ORIG_HTML_HOST:+-v "$ORIG_HTML_HOST":/orig.html:ro -e ORIG_HTML=/orig.html} \
  -v "$REPO":/repo:ro -v "$PW":/pw/node_modules:ro -v "$OUT":/out -w /repo/tests/lab/browser \
  mcr.microsoft.com/playwright:v1.60.0-noble node "$SPEC" || { rc=$?; echo "--- server log (tail) ---"; docker logs "$SRV" 2>&1 | tail -25; exit $rc; }
echo "--- server log (tail) - tracebacks / 5xx would show here ---"; docker logs "$SRV" 2>&1 | grep -E "Traceback|Error|500" | head -10 || true

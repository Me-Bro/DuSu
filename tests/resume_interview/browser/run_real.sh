#!/usr/bin/env bash
# Resume Interview - the browser tier against the REAL app: uvicorn + a SCRATCH Postgres + the stub model (tests/resume_interview/e2e_server.py), a real
# Chromium with a fake microphone in the Playwright image. Everything is removed afterwards; no host port is bound; never the app's own database.
#   tests/resume_interview/browser/run_real.sh [real.spec.cjs]
# Needs the Playwright modules once (see run.sh) and the test image `dusu-ri-test` (see ../README.md).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
IMG="${RI_TEST_IMAGE:-dusu-ri-test}"
PW="${PW_MODULES:-$HOME/.cache/dusu-ri-pwrun/node_modules}"
OUT="${OUT_DIR:-$HOME/.cache/dusu-ri-shots}"
SPEC="${1:-real.spec.cjs}"
mkdir -p "$OUT"
NET="ri-e2e-net-$$"; PG="ri-e2e-pg-$$"; SRV="ri-e2e-srv-$$"
cleanup() { docker rm -f "$SRV" "$PG" >/dev/null 2>&1 || true; docker network rm "$NET" >/dev/null 2>&1 || true; }
trap cleanup EXIT
docker network create "$NET" >/dev/null
docker run -d --name "$PG" --network "$NET" -e POSTGRES_USER=ri -e POSTGRES_PASSWORD=ri -e POSTGRES_DB=ri postgres:18-alpine >/dev/null
for _ in $(seq 1 60); do docker exec "$PG" pg_isready -U ri -d ri >/dev/null 2>&1 && break; sleep 1; done
sleep 2
rm -rf "$REPO/tests/resume_interview/.e2e"
docker run -d --name "$SRV" --network "$NET" \
  -e DATABASE_URL="postgresql://ri:ri@$PG:5432/ri" -e DATABASE_SSL=false -e SESSION_SECRET=ri-e2e-secret -e GOOGLE_CLIENT_ID=e2e-client \
  -e GROQ_API_KEY= -e GEMINI_API_KEY= -e OPENROUTER_API_KEY= -e GITHUB_TOKEN= \
  -v "$REPO/backend":/app -v "$REPO/tests":/tests "$IMG" python /tests/resume_interview/e2e_server.py >/dev/null
for _ in $(seq 1 90); do
  docker exec "$SRV" python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=2)" >/dev/null 2>&1 && break
  sleep 1
done
docker exec "$SRV" python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=2)" >/dev/null 2>&1 || { echo "the e2e server did not come up:"; docker logs "$SRV" 2>&1 | tail -30; exit 3; }
# --network container:... puts the browser in the SERVER's network namespace, so the page is http://localhost:8000 - a secure context. (A plain
# http://<container-name> origin has no navigator.mediaDevices at all, i.e. no microphone; production is https.)
docker run --rm --ipc=host --network "container:$SRV" --user "$(id -u):$(id -g)" -e HOME=/tmp -e NODE_PATH=/pw/node_modules -e OUT=/out -e REPO=/repo -e BASE="http://localhost:8000" \
  -e TOKENS=/repo/tests/resume_interview/.e2e/tokens.json -e VERBOSE \
  -v "$REPO":/repo:ro -v "$PW":/pw/node_modules:ro -v "$OUT":/out -w /repo/tests/resume_interview/browser \
  mcr.microsoft.com/playwright:v1.60.0-noble node "$SPEC" || { rc=$?; echo "--- server log (tail) ---"; docker logs "$SRV" 2>&1 | tail -25; exit $rc; }

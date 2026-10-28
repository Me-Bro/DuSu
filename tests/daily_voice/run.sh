#!/usr/bin/env bash
# Daily Talk vs a locked screen - the SERVER half on SCRATCH infrastructure: a scratch Postgres on an INTERNAL docker network (no route to the internet), every provider key blanked,
# every provider answer scripted (tests/keys/world.py). Never the app's own `dusu-db-1`.
# Needs docker and the test image (see tests/my_day/README.md). Usage:  tests/daily_voice/run.sh [ws_selftest.py]
# DV_BACKEND=<path> runs against a COPY of the backend (mutants.sh); DV_BACKEND=baked runs against the code INSIDE the image (DV_TEST_IMAGE=dusu-backend:latest).
set -euo pipefail
cd "$(dirname "$0")/../.."
IMG="${DV_TEST_IMAGE:-dusu-ri-test}"
BACKEND="${DV_BACKEND:-$PWD/backend}"
MOUNT=(-v "$BACKEND":/app); [ "$BACKEND" = baked ] && MOUNT=()
TEST="${1:-ws_selftest.py}"
NET="dv-test-net-$$"; PG="dv-test-pg-$$"
cleanup() { docker rm -f "$PG" >/dev/null 2>&1 || true; docker network rm "$NET" >/dev/null 2>&1 || true; }
trap cleanup EXIT
docker network create --internal "$NET" >/dev/null
docker run -d --name "$PG" --network "$NET" -e POSTGRES_USER=ky -e POSTGRES_PASSWORD=ky -e POSTGRES_DB=ky postgres:18-alpine >/dev/null
for _ in $(seq 1 60); do docker exec "$PG" pg_isready -U ky -d ky >/dev/null 2>&1 && break; sleep 1; done
sleep 2   # the entrypoint restarts postgres once after initdb
# the bind-mounted backend/ contains the real .env: every provider key is blanked here (a test must never spend or reveal a real key)
docker run --rm --network "$NET" \
  -e DATABASE_URL="postgresql://ky:ky@$PG:5432/ky" -e DATABASE_SSL=false -e SESSION_SECRET=dv-test-secret -e GOOGLE_CLIENT_ID= -e GROQ_API_KEY= -e GEMINI_API_KEY= -e OPENROUTER_API_KEY= -e GITHUB_TOKEN= \
  "${MOUNT[@]}" -v "$PWD/tests":/tests "$IMG" python "/tests/daily_voice/$TEST"

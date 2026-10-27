#!/usr/bin/env bash
# Keys - the per-key engine, the /keys/* endpoints and the walker, on SCRATCH infrastructure: a scratch Postgres on an INTERNAL docker network (no route to the internet,
# so even a bug cannot spend a real key), every provider key blanked, every provider answer scripted by tests/keys/world.py. Never the app's own `dusu-db-1`.
# Needs docker and the test image (see tests/my_day/README.md). Usage:  tests/keys/run.sh [unit.py|selftest.py|parity.py|ws_selftest.py]
# KY_BACKEND=<path> runs against a COPY of the backend (mutants.sh); KY_BACKEND=baked runs against the code INSIDE the image (KY_TEST_IMAGE=dusu-backend:latest).
set -euo pipefail
cd "$(dirname "$0")/../.."
IMG="${KY_TEST_IMAGE:-dusu-ri-test}"
BACKEND="${KY_BACKEND:-$PWD/backend}"
MOUNT=(-v "$BACKEND":/app); [ "$BACKEND" = baked ] && MOUNT=()
TEST="${1:-selftest.py}"
NET="ky-test-net-$$"; PG="ky-test-pg-$$"
cleanup() { docker rm -f "$PG" >/dev/null 2>&1 || true; docker network rm "$NET" >/dev/null 2>&1 || true; }
trap cleanup EXIT
docker network create --internal "$NET" >/dev/null
docker run -d --name "$PG" --network "$NET" -e POSTGRES_USER=ky -e POSTGRES_PASSWORD=ky -e POSTGRES_DB=ky postgres:18-alpine >/dev/null
for _ in $(seq 1 60); do docker exec "$PG" pg_isready -U ky -d ky >/dev/null 2>&1 && break; sleep 1; done
sleep 2   # the entrypoint restarts postgres once after initdb
# the bind-mounted backend/ contains the real .env: every provider key is blanked here (a test must never spend or reveal a real key)
docker run --rm --network "$NET" \
  -e DATABASE_URL="postgresql://ky:ky@$PG:5432/ky" -e DATABASE_SSL=false -e SESSION_SECRET=ky-test-secret -e GOOGLE_CLIENT_ID= -e GROQ_API_KEY= -e GEMINI_API_KEY= -e OPENROUTER_API_KEY= -e GITHUB_TOKEN= \
  "${MOUNT[@]}" -v "$PWD/tests":/tests "$IMG" python "/tests/keys/$TEST"

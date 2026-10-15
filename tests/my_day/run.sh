#!/usr/bin/env bash
# My Day - the real HTTP layer + the real reminder engine on a SCRATCH Postgres (never the app's own `dusu-db-1`), a fake clock and a fake push sender.
# Needs docker and the test image (see README.md). Usage:  tests/my_day/run.sh [selftest.py|unit.py]
set -euo pipefail
cd "$(dirname "$0")/../.."
IMG="${MD_TEST_IMAGE:-dusu-ri-test}"
BACKEND="${MD_BACKEND:-$PWD/backend}"      # a path = run against that COPY of the backend (mutants.sh); "baked" = run against the code INSIDE the image (a built / deployed image)
MOUNT=(-v "$BACKEND":/app); [ "$BACKEND" = baked ] && MOUNT=()
TEST="${1:-selftest.py}"
NET="md-test-net-$$"; PG="md-test-pg-$$"
cleanup() { docker rm -f "$PG" >/dev/null 2>&1 || true; docker network rm "$NET" >/dev/null 2>&1 || true; }
trap cleanup EXIT
docker network create "$NET" >/dev/null
docker run -d --name "$PG" --network "$NET" -e POSTGRES_USER=md -e POSTGRES_PASSWORD=md -e POSTGRES_DB=md postgres:18-alpine >/dev/null
for _ in $(seq 1 60); do docker exec "$PG" pg_isready -U md -d md >/dev/null 2>&1 && break; sleep 1; done
sleep 2   # the entrypoint restarts postgres once after initdb
# the bind-mounted backend/ contains the real .env: every provider key is blanked here (a test must never spend or reveal a real key)
docker run --rm --network "$NET" \
  -e DATABASE_URL="postgresql://md:md@$PG:5432/md" -e DATABASE_SSL=false -e SESSION_SECRET=md-test-secret -e GOOGLE_CLIENT_ID= -e GROQ_API_KEY= -e GEMINI_API_KEY= -e OPENROUTER_API_KEY= -e GITHUB_TOKEN= \
  "${MOUNT[@]}" -v "$PWD/tests":/tests "$IMG" python "/tests/my_day/$TEST"

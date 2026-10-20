#!/usr/bin/env bash
# Notifications - the real HTTP layer + the real delivery engine on a SCRATCH Postgres (never the app's own `dusu-db-1`), a fake clock and a fake push sender.
# Needs docker and the test image (see tests/my_day/README.md). Usage:  tests/notify/run.sh [selftest.py|unit.py]
# Same shape as tests/my_day/run.sh: NT_BACKEND=<path> runs against a COPY of the backend (mutants.sh); NT_BACKEND=baked runs against the code INSIDE the image.
set -euo pipefail
cd "$(dirname "$0")/../.."
IMG="${NT_TEST_IMAGE:-dusu-ri-test}"
BACKEND="${NT_BACKEND:-$PWD/backend}"
MOUNT=(-v "$BACKEND":/app); [ "$BACKEND" = baked ] && MOUNT=()
TEST="${1:-selftest.py}"
NET="nt-test-net-$$"; PG="nt-test-pg-$$"
cleanup() { docker rm -f "$PG" >/dev/null 2>&1 || true; docker network rm "$NET" >/dev/null 2>&1 || true; }
trap cleanup EXIT
docker network create "$NET" >/dev/null
docker run -d --name "$PG" --network "$NET" -e POSTGRES_USER=nt -e POSTGRES_PASSWORD=nt -e POSTGRES_DB=nt postgres:18-alpine >/dev/null
for _ in $(seq 1 60); do docker exec "$PG" pg_isready -U nt -d nt >/dev/null 2>&1 && break; sleep 1; done
sleep 2   # the entrypoint restarts postgres once after initdb
# the bind-mounted backend/ contains the real .env: every provider key is blanked here (a test must never spend or reveal a real key)
docker run --rm --network "$NET" \
  -e DATABASE_URL="postgresql://nt:nt@$PG:5432/nt" -e DATABASE_SSL=false -e SESSION_SECRET=nt-test-secret -e GOOGLE_CLIENT_ID= -e GROQ_API_KEY= -e GEMINI_API_KEY= -e OPENROUTER_API_KEY= -e GITHUB_TOKEN= \
  "${MOUNT[@]}" -v "$PWD/tests":/tests "$IMG" python "/tests/notify/$TEST"

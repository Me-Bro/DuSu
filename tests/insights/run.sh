#!/usr/bin/env bash
# Insights (first-run funnel counters + "Reserve my plan" + the cache validators of GET /) - the real HTTP layer on a SCRATCH Postgres (never the app's own `dusu-db-1`).
# Needs docker and the test image (see tests/my_day/README.md). Usage:  tests/insights/run.sh [selftest.py|unit.py|ws_selftest.py]
# Same shape as tests/notify/run.sh: INS_BACKEND=<path> runs against a COPY of the backend (mutants.sh); INS_BACKEND=baked runs against the code INSIDE the image.
set -euo pipefail
cd "$(dirname "$0")/../.."
IMG="${INS_TEST_IMAGE:-dusu-ri-test}"
BACKEND="${INS_BACKEND:-$PWD/backend}"
MOUNT=(-v "$BACKEND":/app); [ "$BACKEND" = baked ] && MOUNT=()
TEST="${1:-selftest.py}"
NET="ins-test-net-$$"; PG="ins-test-pg-$$"
cleanup() { docker rm -f "$PG" >/dev/null 2>&1 || true; docker network rm "$NET" >/dev/null 2>&1 || true; }
trap cleanup EXIT
docker network create --internal "$NET" >/dev/null
docker run -d --name "$PG" --network "$NET" -e POSTGRES_USER=ins -e POSTGRES_PASSWORD=ins -e POSTGRES_DB=ins postgres:18-alpine >/dev/null
for _ in $(seq 1 60); do docker exec "$PG" pg_isready -U ins -d ins >/dev/null 2>&1 && break; sleep 1; done
sleep 2   # the entrypoint restarts postgres once after initdb
# the bind-mounted backend/ contains the real .env: every provider key is blanked here (a test must never spend or reveal a real key)
docker run --rm --network "$NET" \
  -e DATABASE_URL="postgresql://ins:ins@$PG:5432/ins" -e DATABASE_SSL=false -e SESSION_SECRET=ins-test-secret -e GOOGLE_CLIENT_ID=ins-client -e GROQ_API_KEY= -e GEMINI_API_KEY= -e OPENROUTER_API_KEY= -e GITHUB_TOKEN= \
  "${MOUNT[@]}" -v "$PWD/tests":/tests "$IMG" python "/tests/insights/$TEST"

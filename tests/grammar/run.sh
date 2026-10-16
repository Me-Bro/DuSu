#!/usr/bin/env bash
# Grammar Coach - tier 2: the real HTTP layer on a SCRATCH Postgres (never the app's own database), stub model.
# Needs docker and the test image `dusu-ri-test` (the app image + pypdf; see tests/resume_interview/README.md). Usage:  tests/grammar/run.sh [selftest.py|ws_harness.py]
set -euo pipefail
cd "$(dirname "$0")/../.."
IMG="${GC_TEST_IMAGE:-dusu-ri-test}"
TEST="${1:-selftest.py}"
NET="gc-test-net-$$"; PG="gc-test-pg-$$"
cleanup() { docker rm -f "$PG" >/dev/null 2>&1 || true; docker network rm "$NET" >/dev/null 2>&1 || true; }
trap cleanup EXIT
docker network create "$NET" >/dev/null
docker run -d --name "$PG" --network "$NET" -e POSTGRES_USER=gc -e POSTGRES_PASSWORD=gc -e POSTGRES_DB=gc postgres:18-alpine >/dev/null
for _ in $(seq 1 60); do docker exec "$PG" pg_isready -U gc -d gc >/dev/null 2>&1 && break; sleep 1; done
sleep 2   # the entrypoint restarts postgres once after initdb
docker run --rm --network "$NET" \
  -e DATABASE_URL="postgresql://gc:gc@$PG:5432/gc" -e DATABASE_SSL=false -e SESSION_SECRET=gc-test-secret -e GOOGLE_CLIENT_ID=gc-test-client -e GROQ_API_KEY= -e GEMINI_API_KEY= -e OPENROUTER_API_KEY= -e GITHUB_TOKEN= \
  -v "${GC_BACKEND_DIR:-$PWD/backend}":/app -v "$PWD/tests":/tests "$IMG" python "/tests/grammar/$TEST"

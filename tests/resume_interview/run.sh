#!/usr/bin/env bash
# Resume Interview - tier 2: the real HTTP layer on a SCRATCH Postgres (never the app's own database), stub model + stub speech-to-text.
# Needs docker and the test image (see README.md). Usage:  tests/resume_interview/run.sh [selftest.py|unit.py]
set -euo pipefail
cd "$(dirname "$0")/../.."
IMG="${RI_TEST_IMAGE:-dusu-ri-test}"
TEST="${1:-selftest.py}"
NET="ri-test-net-$$"; PG="ri-test-pg-$$"
cleanup() { docker rm -f "$PG" >/dev/null 2>&1 || true; docker network rm "$NET" >/dev/null 2>&1 || true; }
trap cleanup EXIT
docker network create "$NET" >/dev/null
docker run -d --name "$PG" --network "$NET" -e POSTGRES_USER=ri -e POSTGRES_PASSWORD=ri -e POSTGRES_DB=ri postgres:18-alpine >/dev/null
for _ in $(seq 1 60); do docker exec "$PG" pg_isready -U ri -d ri >/dev/null 2>&1 && break; sleep 1; done
sleep 2   # the entrypoint restarts postgres once after initdb
docker run --rm --network "$NET" \
  -e DATABASE_URL="postgresql://ri:ri@$PG:5432/ri" -e DATABASE_SSL=false -e SESSION_SECRET=ri-test-secret -e GOOGLE_CLIENT_ID= -e GROQ_API_KEY= -e GEMINI_API_KEY= -e OPENROUTER_API_KEY= -e GITHUB_TOKEN= \
  -v "$PWD/backend":/app -v "$PWD/tests":/tests "$IMG" python "/tests/resume_interview/$TEST"

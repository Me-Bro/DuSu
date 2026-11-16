#!/usr/bin/env bash
# The store layer (backend/app/store) on SCRATCH infrastructure: a scratch MongoDB (a one-member replica set, like the shared one) and, for the differential tests,
# a scratch Postgres - both on an INTERNAL docker network, never the shared `rooted-mongo`, never `dusu-db-1`.
# Needs docker and the test image:  printf 'FROM dusu-backend:latest\nRUN pip install --no-cache-dir pymongo==4.20.0\n' | docker build -t dusu-mongo-test -f - .
# Usage:  tests/store/run.sh [unit.py|differential.py|concurrency.py|...]      (STORE_PG=0 skips the scratch Postgres)
# STORE_BACKEND=<path> runs against a COPY of the backend (mutants.sh); STORE_BACKEND=baked runs against the code INSIDE the image (STORE_TEST_IMAGE=dusu-backend:latest).
set -euo pipefail
cd "$(dirname "$0")/../.."
. tests/lib/scratch_mongo.sh
IMG="${STORE_TEST_IMAGE:-dusu-mongo-test}"
BACKEND="${STORE_BACKEND:-$PWD/backend}"
MOUNT=(-v "$BACKEND":/app); [ "$BACKEND" = baked ] && MOUNT=()
TEST="${1:-unit.py}"
NET="st-test-net-$$"; MG="st-scratch-mongo-$$"; PG="st-scratch-pg-$$"
cleanup() { docker rm -f "$MG" "$PG" >/dev/null 2>&1 || true; docker network rm "$NET" >/dev/null 2>&1 || true; }
trap cleanup EXIT
docker network create --internal "$NET" >/dev/null
scratch_mongo_up "$NET" "$MG"
PGENV=()
if [ "${STORE_PG:-1}" = 1 ]; then scratch_pg_up "$NET" "$PG"; PGENV=(-e PG_URL="postgresql://sc:sc@$PG:5432/sc"); fi
docker run --rm --network "$NET" \
  -e MONGODB_URI="$(scratch_mongo_uri "$MG" st)" -e DUSU_SCRATCH_ONLY=1 "${PGENV[@]}" \
  -e SESSION_SECRET=st-test-secret -e GOOGLE_CLIENT_ID= -e GROQ_API_KEY= -e GEMINI_API_KEY= -e OPENROUTER_API_KEY= -e GITHUB_TOKEN= \
  "${MOUNT[@]}" -v "$PWD/tests":/tests "$IMG" python -u "/tests/store/$TEST" "${@:2}"

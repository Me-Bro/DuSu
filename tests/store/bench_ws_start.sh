#!/usr/bin/env bash
# Time how long a chat takes to open (tests/store/bench_ws_start.py): "old" = the tree from before the migration on a scratch Postgres, "new" = this tree on a scratch Mongo.
#   tests/store/bench_ws_start.sh old|new       (scratch databases on an internal network; never the shared Mongo, never dusu-db-1)
set -euo pipefail
cd "$(dirname "$0")/../.."
. tests/lib/scratch_mongo.sh
WHICH="${1:-new}"
IMG="${STORE_TEST_IMAGE:-dusu-mongo-test}"
OLD="$PWD/tests/store/.old/backend"
NET="bw-test-net-$$"; MG="bw-scratch-mongo-$$"; PG="bw-scratch-pg-$$"
cleanup() { docker rm -f "$MG" "$PG" >/dev/null 2>&1 || true; docker network rm "$NET" >/dev/null 2>&1 || true; }
trap cleanup EXIT
docker network create --internal "$NET" >/dev/null
COMMON=(-e SESSION_SECRET=bench-secret -e GOOGLE_CLIENT_ID= -e GROQ_API_KEY= -e GEMINI_API_KEY= -e OPENROUTER_API_KEY= -e GITHUB_TOKEN= -e PYTHONUNBUFFERED=1 -e BENCH_RUNS="${BENCH_RUNS:-25}" -v "$PWD/tests":/tests)
if [ "$WHICH" = old ]; then
  scratch_pg_up "$NET" "$PG"
  docker run --rm --network "$NET" -e DATABASE_URL="postgresql://sc:sc@$PG:5432/sc" -e DATABASE_SSL=false "${COMMON[@]}" -v "$OLD":/app "$IMG" python -u /tests/store/bench_ws_start.py
else
  scratch_mongo_up "$NET" "$MG"
  docker run --rm --network "$NET" -e MONGODB_URI="$(scratch_mongo_uri "$MG" bench)" -e DUSU_SCRATCH_ONLY=1 "${COMMON[@]}" -v "$PWD/backend":/app "$IMG" python -u /tests/store/bench_ws_start.py
fi

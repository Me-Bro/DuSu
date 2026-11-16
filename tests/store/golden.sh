#!/usr/bin/env bash
# Golden master for app/db.py: the SAME scenario (tests/store/golden_db.py) on the OLD tree (tests/store/.old/backend = the commit before the migration, on a scratch Postgres)
# and on the NEW tree (this working tree, on a scratch Mongo); the recorded return values and the final contents of every table must be identical.
#   tests/store/golden.sh [core|full] [old|new|both]
# Everything runs on an INTERNAL docker network with scratch databases - never the shared rooted-mongo, never dusu-db-1.
set -euo pipefail
cd "$(dirname "$0")/../.."
. tests/lib/scratch_mongo.sh
PHASE="${1:-core}"; WHICH="${2:-both}"
IMG="${STORE_TEST_IMAGE:-dusu-mongo-test}"
OLD="$PWD/tests/store/.old/backend"
[ -d "$OLD/app" ] || { mkdir -p tests/store/.old; git archive "${GOLDEN_OLD_REV:-8a53a71}" backend | tar -x -C tests/store/.old; }
mkdir -p tests/store/.out
NET="gm-test-net-$$"; MG="gm-scratch-mongo-$$"; PG="gm-scratch-pg-$$"
cleanup() { docker rm -f "$MG" "$PG" >/dev/null 2>&1 || true; docker network rm "$NET" >/dev/null 2>&1 || true; }
trap cleanup EXIT
docker network create --internal "$NET" >/dev/null
COMMON=(-e SESSION_SECRET=golden-secret -e GOOGLE_CLIENT_ID= -e GROQ_API_KEY= -e GEMINI_API_KEY= -e OPENROUTER_API_KEY= -e GITHUB_TOKEN= -e PYTHONHASHSEED=0 -e GOLDEN_PHASE="$PHASE" -v "$PWD/tests":/tests)
if [ "$WHICH" != new ]; then
  scratch_pg_up "$NET" "$PG"
  echo "== OLD tree on Postgres"
  docker run --rm --network "$NET" -e DATABASE_URL="postgresql://sc:sc@$PG:5432/sc" -e DATABASE_SSL=false -e GOLDEN_OUT=/tests/store/.out/golden_old.json "${COMMON[@]}" -v "$OLD":/app "$IMG" python -u /tests/store/golden_db.py
fi
if [ "$WHICH" != old ]; then
  scratch_mongo_up "$NET" "$MG"
  echo "== NEW tree on Mongo"
  docker run --rm --network "$NET" -e MONGODB_URI="$(scratch_mongo_uri "$MG" golden)" -e DUSU_SCRATCH_ONLY=1 -e GOLDEN_OUT=/tests/store/.out/golden_new.json "${COMMON[@]}" -v "$PWD/backend":/app "$IMG" python -u /tests/store/golden_db.py
fi
if [ "$WHICH" = both ]; then
  echo "== diff"
  python3 tests/store/golden_diff.py tests/store/.out/golden_old.json tests/store/.out/golden_new.json
fi

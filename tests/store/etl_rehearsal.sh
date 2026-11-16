#!/usr/bin/env bash
# Rehearse the migration on REAL data. Production is only READ (one pg_dump); everything else happens in scratch containers on an INTERNAL docker network:
#   a fresh dump of the live Postgres (kept in ~/dusu-backups, mode 600)  ->  a scratch Postgres  ->  shadow answers from the OLD tree
#   ->  the ETL into a scratch Mongo + its row-by-row verifier  ->  shadow answers from the NEW tree  ->  the two sets of answers diffed.
#   tests/store/etl_rehearsal.sh [existing-dump.sql.gz]
# The dump holds personal data (emails, memory, sealed keys): it never leaves this machine and nothing here prints a row.
set -euo pipefail
cd "$(dirname "$0")/../.."
. tests/lib/scratch_mongo.sh
IMG="${STORE_TEST_IMAGE:-dusu-mongo-test}"
OLD="$PWD/tests/store/.old/backend"
[ -d "$OLD/app" ] || { mkdir -p tests/store/.old; git archive "${GOLDEN_OLD_REV:-8a53a71}" backend | tar -x -C tests/store/.old; }
mkdir -p "$HOME/dusu-backups" tests/store/.out
DUMP="${1:-}"
if [ -z "$DUMP" ]; then
  DUMP="$HOME/dusu-backups/dusu-rehearsal-$(date +%Y%m%d-%H%M%S).sql.gz"
  ( umask 077; docker exec dusu-db-1 sh -c 'pg_dump --no-owner --no-acl -U "$POSTGRES_USER" -d "$POSTGRES_DB"' | gzip > "$DUMP" )
  echo "dump: $DUMP ($(du -h "$DUMP" | cut -f1))"
fi
NET="etl-test-net-$$"; PG="etl-scratch-pg-$$"; MG="etl-scratch-mongo-$$"
cleanup() { docker rm -f "$PG" "$MG" >/dev/null 2>&1 || true; docker network rm "$NET" >/dev/null 2>&1 || true; }
trap cleanup EXIT
docker network create --internal "$NET" >/dev/null
scratch_pg_up "$NET" "$PG"
scratch_mongo_up "$NET" "$MG"
gunzip -c "$DUMP" | docker exec -i "$PG" psql -q -U sc -d sc >/dev/null 2>tests/store/.out/restore.err || true
echo "restored: $(docker exec "$PG" psql -U sc -d sc -At -c 'select count(*) from users') user(s), $(docker exec "$PG" psql -U sc -d sc -At -c "select count(*) from pg_tables where schemaname='public'") table(s)"
COMMON=(-e SESSION_SECRET=shadow-secret -e GOOGLE_CLIENT_ID= -e GROQ_API_KEY= -e GEMINI_API_KEY= -e OPENROUTER_API_KEY= -e GITHUB_TOKEN= -e PYTHONUNBUFFERED=1 -e PYTHONHASHSEED=0 -v "$PWD/tests":/tests)
PGURL="postgresql://sc:sc@$PG:5432/sc"
echo "== 1. the ETL (on the PRISTINE restore: a GET can write, so the copy is taken before anyone reads): restored Postgres -> scratch Mongo (and its verifier)"
docker run --rm --network "$NET" -e MONGODB_URI="$(scratch_mongo_uri "$MG" dusu)" -e DUSU_SCRATCH_ONLY=1 -e SRC_DATABASE_URL="$PGURL" "${COMMON[@]}" -v "$PWD/backend":/app "$IMG" python /app/scripts/pg_to_mongo.py --verify
echo "== 2. shadow answers: the OLD tree on the restored Postgres"
docker run --rm --network "$NET" -e DATABASE_URL="$PGURL" -e DATABASE_SSL=false -e SHADOW_OUT=/tests/store/.out/shadow_old.json "${COMMON[@]}" -v "$OLD":/app "$IMG" python /tests/store/shadow.py
echo "== 3. shadow answers: the NEW tree on the migrated Mongo"
docker run --rm --network "$NET" -e MONGODB_URI="$(scratch_mongo_uri "$MG" dusu)" -e DUSU_SCRATCH_ONLY=1 -e SHADOW_OUT=/tests/store/.out/shadow_new.json "${COMMON[@]}" -v "$PWD/backend":/app "$IMG" python /tests/store/shadow.py
echo "== 4. diff"
python3 tests/store/shadow_diff.py tests/store/.out/shadow_old.json tests/store/.out/shadow_new.json

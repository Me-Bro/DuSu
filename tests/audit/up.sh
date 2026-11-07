#!/usr/bin/env bash
# Start the audit app and LEAVE IT RUNNING (stop it with tests/audit/down.sh): a scratch Postgres on an INTERNAL docker network (no route out, never the app's own database)
# + the real app with the fake model and the seeded learners of tests/audit/audit_server.py. Specs run against it with tests/audit/spec.sh.
#   tests/audit/up.sh
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
IMG="${AUDIT_IMAGE:-dusu-ri-test}"
BACKEND="${AUDIT_BACKEND:-$REPO/backend}"   # a path = run against that COPY of the backend; "baked" = run the code INSIDE the image (AUDIT_IMAGE=dusu-backend:latest) - what a deploy tests
MOUNT=(-v "$BACKEND":/app); [ "$BACKEND" = baked ] && MOUNT=()
mkdir -p "$HERE/.out"
if [ -f "$HERE/.out/env" ]; then echo "already up ($(cat "$HERE/.out/env" | tr '\n' ' ')) - run tests/audit/down.sh first"; exit 1; fi
ID="$$"; NET="aud-net-$ID"; PG="aud-pg-$ID"; SRV="aud-srv-$ID"
docker network create --internal "$NET" >/dev/null
docker run -d --name "$PG" --network "$NET" -e POSTGRES_USER=au -e POSTGRES_PASSWORD=au -e POSTGRES_DB=au postgres:18-alpine >/dev/null
for _ in $(seq 1 60); do docker exec "$PG" pg_isready -U au -d au >/dev/null 2>&1 && break; sleep 1; done
sleep 2
rm -f "$HERE/.out/tokens.json"
docker run -d --name "$SRV" --network "$NET" \
  -e DATABASE_URL="postgresql://au:au@$PG:5432/au" -e DATABASE_SSL=false -e SESSION_SECRET=audit-secret -e GOOGLE_CLIENT_ID=audit-client \
  -e GROQ_API_KEY= -e GEMINI_API_KEY= -e OPENROUTER_API_KEY= -e GITHUB_TOKEN= \
  "${MOUNT[@]}" -v "$REPO/tests":/tests "$IMG" python /tests/audit/audit_server.py >/dev/null
for _ in $(seq 1 120); do
  docker exec "$SRV" python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=2)" >/dev/null 2>&1 && break
  sleep 1
done
docker exec "$SRV" python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=2)" >/dev/null 2>&1 || { echo "the audit server did not come up:"; docker logs "$SRV" 2>&1 | tail -30; docker rm -f "$SRV" "$PG" >/dev/null 2>&1; docker network rm "$NET" >/dev/null 2>&1; exit 3; }
printf '%s\n%s\n%s\n' "$NET" "$PG" "$SRV" > "$HERE/.out/env"
echo "audit app is up: server=$SRV db=$PG net=$NET   tokens: $HERE/.out/tokens.json"

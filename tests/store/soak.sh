#!/usr/bin/env bash
# The soak + explain gate (M6): the three background loops against a SCRATCH MongoDB with the profiler on. Never the shared `rooted-mongo`.
#   tests/store/soak.sh                       (SOAK_LEARNERS=300 SOAK_SECONDS=300 by default; ~7 minutes with seeding)
#   SOAK_IMAGE=dusu-backend:mongo-rc1 SOAK_BACKEND=baked tests/store/soak.sh      against the code inside a built image
set -euo pipefail
cd "$(dirname "$0")/../.."
. tests/lib/scratch_mongo.sh
IMG="${SOAK_IMAGE:-dusu-mongo-test}"
BACKEND="${SOAK_BACKEND:-$PWD/backend}"
MOUNT=(-v "$BACKEND":/app); [ "$BACKEND" = baked ] && MOUNT=()
NET="sk-test-net-$$"; MG="sk-scratch-mongo-$$"
cleanup() { docker rm -f "$MG" >/dev/null 2>&1 || true; docker network rm "$NET" >/dev/null 2>&1 || true; }
trap cleanup EXIT
docker network create --internal "$NET" >/dev/null
scratch_mongo_up "$NET" "$MG"
docker run --rm --network "$NET" \
  -e MONGODB_URI="$(scratch_mongo_uri "$MG" soak)" -e DUSU_SCRATCH_ONLY=1 \
  -e SOAK_LEARNERS="${SOAK_LEARNERS:-300}" -e SOAK_SECONDS="${SOAK_SECONDS:-300}" \
  -e SESSION_SECRET=soak-test-secret -e GOOGLE_CLIENT_ID= -e GROQ_API_KEY= -e GEMINI_API_KEY= -e OPENROUTER_API_KEY= -e GITHUB_TOKEN= \
  "${MOUNT[@]}" -v "$PWD/tests":/tests "$IMG" python -u /tests/store/soak.py

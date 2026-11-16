#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
. tests/lib/scratch_mongo.sh
IMG="${PROF_IMAGE:-dusu-mongo-test}"; BACKEND="${PROF_BACKEND:-$PWD/backend}"; MOUNT=(-v "$BACKEND":/app); [ "$BACKEND" = baked ] && MOUNT=()
NET="pf-test-net-$$"; MG="pf-scratch-mongo-$$"
trap 'docker rm -f "$MG" >/dev/null 2>&1 || true; docker network rm "$NET" >/dev/null 2>&1 || true' EXIT
docker network create --internal "$NET" >/dev/null
scratch_mongo_up "$NET" "$MG"
docker run --rm --network "$NET" -e MONGODB_URI="$(scratch_mongo_uri "$MG" prof)" -e DUSU_SCRATCH_ONLY=1 -e PROF_LEARNERS="${PROF_LEARNERS:-150}" -e SESSION_SECRET=prof -e GROQ_API_KEY= -e GEMINI_API_KEY= -e OPENROUTER_API_KEY= -e PYTHONUNBUFFERED=1 "${MOUNT[@]}" -v "$PWD/tests":/tests "$IMG" python -u /tests/store/prof_materialize.py

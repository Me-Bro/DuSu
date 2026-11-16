#!/usr/bin/env bash
# Daily Talk vs a locked screen - the SERVER half on SCRATCH infrastructure: a scratch MongoDB on an INTERNAL docker network (no route to the internet), every provider key blanked,
# every provider answer scripted (tests/keys/world.py). Never the shared `rooted-mongo`.
# Needs docker and the test image (see tests/my_day/README.md). Usage:  tests/daily_voice/run.sh [ws_selftest.py]
# DV_BACKEND=<path> runs against a COPY of the backend (mutants.sh); DV_BACKEND=baked runs against the code INSIDE the image (DV_TEST_IMAGE=dusu-backend:latest).
set -euo pipefail
cd "$(dirname "$0")/../.."
. tests/lib/scratch_mongo.sh
IMG="${DV_TEST_IMAGE:-dusu-mongo-test}"
BACKEND="${DV_BACKEND:-$PWD/backend}"
MOUNT=(-v "$BACKEND":/app); [ "$BACKEND" = baked ] && MOUNT=()
TEST="${1:-ws_selftest.py}"
NET="dv-test-net-$$"; MG="dv-scratch-mongo-$$"
cleanup() { docker rm -f "$MG" >/dev/null 2>&1 || true; docker network rm "$NET" >/dev/null 2>&1 || true; }
trap cleanup EXIT
docker network create --internal "$NET" >/dev/null
scratch_mongo_up "$NET" "$MG"
# the bind-mounted backend/ contains the real .env: every provider key is blanked here (a test must never spend or reveal a real key)
docker run --rm --network "$NET" \
  -e PYTHONUNBUFFERED=1 -e MONGODB_URI="$(scratch_mongo_uri "$MG" ky)" -e DUSU_SCRATCH_ONLY=1 -e SESSION_SECRET=dv-test-secret -e GOOGLE_CLIENT_ID= -e GROQ_API_KEY= -e GEMINI_API_KEY= -e OPENROUTER_API_KEY= -e GITHUB_TOKEN= \
  "${MOUNT[@]}" -v "$PWD/tests":/tests "$IMG" python "/tests/daily_voice/$TEST"

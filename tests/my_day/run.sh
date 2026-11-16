#!/usr/bin/env bash
# My Day - the real HTTP layer + the real reminder engine on a SCRATCH MongoDB (a one-member replica set) (never the shared `rooted-mongo`), a fake clock and a fake push sender.
# Needs docker and the test image (see README.md). Usage:  tests/my_day/run.sh [selftest.py|unit.py]
set -euo pipefail
cd "$(dirname "$0")/../.."
. tests/lib/scratch_mongo.sh
IMG="${MD_TEST_IMAGE:-dusu-mongo-test}"
BACKEND="${MD_BACKEND:-$PWD/backend}"      # a path = run against that COPY of the backend (mutants.sh); "baked" = run against the code INSIDE the image (a built / deployed image)
MOUNT=(-v "$BACKEND":/app); [ "$BACKEND" = baked ] && MOUNT=()
TEST="${1:-selftest.py}"
NET="md-test-net-$$"; MG="md-scratch-mongo-$$"
cleanup() { docker rm -f "$MG" >/dev/null 2>&1 || true; docker network rm "$NET" >/dev/null 2>&1 || true; }
trap cleanup EXIT
docker network create "$NET" >/dev/null
scratch_mongo_up "$NET" "$MG"
# the bind-mounted backend/ contains the real .env: every provider key is blanked here (a test must never spend or reveal a real key)
docker run --rm --network "$NET" \
  -e PYTHONUNBUFFERED=1 -e MONGODB_URI="$(scratch_mongo_uri "$MG" md)" -e DUSU_SCRATCH_ONLY=1 -e SESSION_SECRET=md-test-secret -e GOOGLE_CLIENT_ID= -e GROQ_API_KEY= -e GEMINI_API_KEY= -e OPENROUTER_API_KEY= -e GITHUB_TOKEN= \
  "${MOUNT[@]}" -v "$PWD/tests":/tests "$IMG" python "/tests/my_day/$TEST"

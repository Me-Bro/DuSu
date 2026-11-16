#!/usr/bin/env bash
# Resume Interview - tier 2: the real HTTP layer on a SCRATCH MongoDB (a one-member replica set) (never the app's own database), stub model + stub speech-to-text.
# Needs docker and the test image (see README.md). Usage:  tests/resume_interview/run.sh [selftest.py|unit.py]
set -euo pipefail
cd "$(dirname "$0")/../.."
. tests/lib/scratch_mongo.sh
IMG="${RI_TEST_IMAGE:-dusu-mongo-test}"
BACKEND="${RI_BACKEND:-$PWD/backend}"      # "baked" = test the code INSIDE the image (a built / deployed image) instead of a bind mount
MOUNT=(-v "$BACKEND":/app); [ "$BACKEND" = baked ] && MOUNT=()
TEST="${1:-selftest.py}"
NET="ri-test-net-$$"; MG="ri-scratch-mongo-$$"
cleanup() { docker rm -f "$MG" >/dev/null 2>&1 || true; docker network rm "$NET" >/dev/null 2>&1 || true; }
trap cleanup EXIT
docker network create "$NET" >/dev/null
scratch_mongo_up "$NET" "$MG"
docker run --rm --network "$NET" \
  -e PYTHONUNBUFFERED=1 -e MONGODB_URI="$(scratch_mongo_uri "$MG" ri)" -e DUSU_SCRATCH_ONLY=1 -e SESSION_SECRET=ri-test-secret -e GOOGLE_CLIENT_ID= -e GROQ_API_KEY= -e GEMINI_API_KEY= -e OPENROUTER_API_KEY= -e GITHUB_TOKEN= \
  "${MOUNT[@]}" -v "$PWD/tests":/tests "$IMG" python "/tests/resume_interview/$TEST"

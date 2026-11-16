#!/usr/bin/env bash
# Insights (first-run funnel counters + "Reserve my plan" + the cache validators of GET /) - the real HTTP layer on a SCRATCH MongoDB (a one-member replica set) (never the shared `rooted-mongo`).
# Needs docker and the test image (see tests/my_day/README.md). Usage:  tests/insights/run.sh [selftest.py|unit.py|ws_selftest.py]
# Same shape as tests/notify/run.sh: INS_BACKEND=<path> runs against a COPY of the backend (mutants.sh); INS_BACKEND=baked runs against the code INSIDE the image.
set -euo pipefail
cd "$(dirname "$0")/../.."
. tests/lib/scratch_mongo.sh
IMG="${INS_TEST_IMAGE:-dusu-mongo-test}"
BACKEND="${INS_BACKEND:-$PWD/backend}"
MOUNT=(-v "$BACKEND":/app); [ "$BACKEND" = baked ] && MOUNT=()
TEST="${1:-selftest.py}"
NET="ins-test-net-$$"; MG="ins-scratch-mongo-$$"
cleanup() { docker rm -f "$MG" >/dev/null 2>&1 || true; docker network rm "$NET" >/dev/null 2>&1 || true; }
trap cleanup EXIT
docker network create --internal "$NET" >/dev/null
scratch_mongo_up "$NET" "$MG"
# the bind-mounted backend/ contains the real .env: every provider key is blanked here (a test must never spend or reveal a real key)
docker run --rm --network "$NET" \
  -e PYTHONUNBUFFERED=1 -e MONGODB_URI="$(scratch_mongo_uri "$MG" ins)" -e DUSU_SCRATCH_ONLY=1 -e SESSION_SECRET=ins-test-secret -e GOOGLE_CLIENT_ID=ins-client -e GROQ_API_KEY= -e GEMINI_API_KEY= -e OPENROUTER_API_KEY= -e GITHUB_TOKEN= \
  "${MOUNT[@]}" -v "$PWD/tests":/tests "$IMG" python "/tests/insights/$TEST"

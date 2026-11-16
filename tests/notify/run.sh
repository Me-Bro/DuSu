#!/usr/bin/env bash
# Notifications - the real HTTP layer + the real delivery engine on a SCRATCH MongoDB (a one-member replica set) (never the shared `rooted-mongo`), a fake clock and a fake push sender.
# Needs docker and the test image (see tests/my_day/README.md). Usage:  tests/notify/run.sh [selftest.py|unit.py]
# Same shape as tests/my_day/run.sh: NT_BACKEND=<path> runs against a COPY of the backend (mutants.sh); NT_BACKEND=baked runs against the code INSIDE the image.
set -euo pipefail
cd "$(dirname "$0")/../.."
. tests/lib/scratch_mongo.sh
IMG="${NT_TEST_IMAGE:-dusu-mongo-test}"
BACKEND="${NT_BACKEND:-$PWD/backend}"
MOUNT=(-v "$BACKEND":/app); [ "$BACKEND" = baked ] && MOUNT=()
TEST="${1:-selftest.py}"
NET="nt-test-net-$$"; MG="nt-scratch-mongo-$$"
cleanup() { docker rm -f "$MG" >/dev/null 2>&1 || true; docker network rm "$NET" >/dev/null 2>&1 || true; }
trap cleanup EXIT
docker network create "$NET" >/dev/null
scratch_mongo_up "$NET" "$MG"
# the bind-mounted backend/ contains the real .env: every provider key is blanked here (a test must never spend or reveal a real key)
docker run --rm --network "$NET" \
  -e PYTHONUNBUFFERED=1 -e MONGODB_URI="$(scratch_mongo_uri "$MG" nt)" -e DUSU_SCRATCH_ONLY=1 -e SESSION_SECRET=nt-test-secret -e GOOGLE_CLIENT_ID= -e GROQ_API_KEY= -e GEMINI_API_KEY= -e OPENROUTER_API_KEY= -e GITHUB_TOKEN= \
  "${MOUNT[@]}" -v "$PWD/tests":/tests "$IMG" python "/tests/notify/$TEST"

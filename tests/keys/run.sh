#!/usr/bin/env bash
# Keys - the per-key engine, the /keys/* endpoints and the walker, on SCRATCH infrastructure: a scratch MongoDB on an INTERNAL docker network (no route to the internet,
# so even a bug cannot spend a real key), every provider key blanked, every provider answer scripted by tests/keys/world.py. Never the shared `rooted-mongo`.
# Needs docker and the test image (see tests/my_day/README.md). Usage:  tests/keys/run.sh [unit.py|selftest.py|parity.py|ws_selftest.py]
# KY_BACKEND=<path> runs against a COPY of the backend (mutants.sh); KY_BACKEND=baked runs against the code INSIDE the image (KY_TEST_IMAGE=dusu-backend:latest).
set -euo pipefail
cd "$(dirname "$0")/../.."
. tests/lib/scratch_mongo.sh
IMG="${KY_TEST_IMAGE:-dusu-mongo-test}"
BACKEND="${KY_BACKEND:-$PWD/backend}"
MOUNT=(-v "$BACKEND":/app); [ "$BACKEND" = baked ] && MOUNT=()
TEST="${1:-selftest.py}"
NET="ky-test-net-$$"; MG="ky-scratch-mongo-$$"
cleanup() { docker rm -f "$MG" >/dev/null 2>&1 || true; docker network rm "$NET" >/dev/null 2>&1 || true; }
trap cleanup EXIT
docker network create --internal "$NET" >/dev/null
scratch_mongo_up "$NET" "$MG"
# the bind-mounted backend/ contains the real .env: every provider key is blanked here (a test must never spend or reveal a real key)
docker run --rm --network "$NET" \
  -e PYTHONUNBUFFERED=1 -e MONGODB_URI="$(scratch_mongo_uri "$MG" ky)" -e DUSU_SCRATCH_ONLY=1 -e SESSION_SECRET=ky-test-secret -e GOOGLE_CLIENT_ID= -e GROQ_API_KEY= -e GEMINI_API_KEY= -e OPENROUTER_API_KEY= -e GITHUB_TOKEN= \
  "${MOUNT[@]}" -v "$PWD/tests":/tests "$IMG" python "/tests/keys/$TEST"

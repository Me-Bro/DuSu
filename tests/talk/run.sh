#!/usr/bin/env bash
# Talk - the server tiers, on SCRATCH infrastructure only: a scratch MongoDB on an `--internal` docker network (never the app's own database, never the shared `rooted-mongo`), scripted fake models,
# NO provider key.  Needs docker and the test image `dusu-mongo-test`.
#
#   tests/talk/run.sh [--nomongo] <test.py>        e.g.  tests/talk/run.sh selftest.py   |   tests/talk/run.sh --nomongo unit_engine.py
#
#   TALK_BACKEND_DIR=<dir>   test a COPY of the backend (planted bugs, or tests/.baselines/lab-done/backend for the "old" side of the parity run)
#   TALK_BACKEND_DIR=baked   test the code INSIDE the image (set TALK_TEST_IMAGE=dusu-backend:<tag> for a built image)
#   TALK_ENV="K=V K2=V2"     extra environment for the test process (parity_ws.py uses TALK_LABEL / TALK_OUT)
# Pure tiers need no docker at all:  python3 tests/talk/unit_topics.py   python3 tests/talk/unit_reply.py   python3 tests/talk/parity_compare.py
set -euo pipefail
cd "$(dirname "$0")/../.."
NOMONGO=0
if [ "${1:-}" = "--nomongo" ]; then NOMONGO=1; shift; fi
TEST="${1:?usage: tests/talk/run.sh [--nomongo] <test.py>}"
IMG="${TALK_TEST_IMAGE:-dusu-mongo-test}"
MOUNT=(-v "${TALK_BACKEND_DIR:-$PWD/backend}":/app); [ "${TALK_BACKEND_DIR:-}" = baked ] && MOUNT=()
EXTRA=(); for kv in ${TALK_ENV:-}; do EXTRA+=(-e "$kv"); done
COMMON=(-e PYTHONUNBUFFERED=1 -e DUSU_SCRATCH_ONLY=1 -e SESSION_SECRET=talk-test-secret -e GOOGLE_CLIENT_ID=talk-test-client -e GROQ_API_KEY= -e GEMINI_API_KEY= -e OPENROUTER_API_KEY= -e GITHUB_TOKEN=
        "${MOUNT[@]}" -v "$PWD/tests":/tests)
if [ "$NOMONGO" = 1 ]; then
  docker run --rm --network none "${COMMON[@]}" "${EXTRA[@]}" "$IMG" python "/tests/talk/$TEST"
  exit $?
fi
. tests/lib/scratch_mongo.sh
NET="talk-test-net-$$"; MG="talk-scratch-mongo-$$"
cleanup() { docker rm -f "$MG" >/dev/null 2>&1 || true; docker network rm "$NET" >/dev/null 2>&1 || true; }
trap cleanup EXIT
docker network create --internal "$NET" >/dev/null
scratch_mongo_up "$NET" "$MG"
docker run --rm --network "$NET" -e MONGODB_URI="$(scratch_mongo_uri "$MG" talk)" "${COMMON[@]}" "${EXTRA[@]}" "$IMG" python "/tests/talk/$TEST"

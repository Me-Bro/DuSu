#!/usr/bin/env bash
# Grammar Coach - tier 2: the real HTTP layer on a SCRATCH MongoDB (a one-member replica set) (never the app's own database), stub model.
# Needs docker and the test image `dusu-mongo-test` (the app image + pypdf; see tests/resume_interview/README.md). Usage:  tests/grammar/run.sh [selftest.py|ws_harness.py]
set -euo pipefail
cd "$(dirname "$0")/../.."
. tests/lib/scratch_mongo.sh
IMG="${GC_TEST_IMAGE:-dusu-mongo-test}"
TEST="${1:-selftest.py}"
# GC_BACKEND_DIR=<dir> tests a copy (planted bugs); GC_BACKEND_DIR=baked tests the code INSIDE the image (set GC_TEST_IMAGE=dusu-backend:latest for a built image)
MOUNT=(-v "${GC_BACKEND_DIR:-$PWD/backend}":/app); [ "${GC_BACKEND_DIR:-}" = baked ] && MOUNT=()
NET="gc-test-net-$$"; MG="gc-scratch-mongo-$$"
cleanup() { docker rm -f "$MG" >/dev/null 2>&1 || true; docker network rm "$NET" >/dev/null 2>&1 || true; }
trap cleanup EXIT
docker network create "$NET" >/dev/null
scratch_mongo_up "$NET" "$MG"
docker run --rm --network "$NET" \
  -e PYTHONUNBUFFERED=1 -e MONGODB_URI="$(scratch_mongo_uri "$MG" gc)" -e DUSU_SCRATCH_ONLY=1 -e SESSION_SECRET=gc-test-secret -e GOOGLE_CLIENT_ID=gc-test-client -e GROQ_API_KEY= -e GEMINI_API_KEY= -e OPENROUTER_API_KEY= -e GITHUB_TOKEN= \
  "${MOUNT[@]}" -v "$PWD/tests":/tests "$IMG" python "/tests/grammar/$TEST"

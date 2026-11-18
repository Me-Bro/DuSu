#!/usr/bin/env bash
# Grammar Lab - the real HTTP layer on a SCRATCH MongoDB (a one-member replica set; never the app's own database). No model, no key: the Lab makes no AI call.
# Needs docker and the test image `dusu-mongo-test`. Usage:  tests/lab/run.sh [selftest.py]
# LAB_BACKEND_DIR=<dir> tests a copy (planted bugs); LAB_BACKEND_DIR=baked tests the code INSIDE the image (set LAB_TEST_IMAGE=dusu-backend:latest for a built image)
set -euo pipefail
cd "$(dirname "$0")/../.."
. tests/lib/scratch_mongo.sh
IMG="${LAB_TEST_IMAGE:-dusu-mongo-test}"
TEST="${1:-selftest.py}"
MOUNT=(-v "${LAB_BACKEND_DIR:-$PWD/backend}":/app); [ "${LAB_BACKEND_DIR:-}" = baked ] && MOUNT=()
NET="lab-test-net-$$"; MG="lab-scratch-mongo-$$"
cleanup() { docker rm -f "$MG" >/dev/null 2>&1 || true; docker network rm "$NET" >/dev/null 2>&1 || true; }
trap cleanup EXIT
docker network create "$NET" >/dev/null
scratch_mongo_up "$NET" "$MG"
docker run --rm --network "$NET" \
  -e PYTHONUNBUFFERED=1 -e MONGODB_URI="$(scratch_mongo_uri "$MG" lab)" -e DUSU_SCRATCH_ONLY=1 -e SESSION_SECRET=lab-test-secret -e GOOGLE_CLIENT_ID=lab-test-client -e GROQ_API_KEY= -e GEMINI_API_KEY= -e OPENROUTER_API_KEY= -e GITHUB_TOKEN= \
  "${MOUNT[@]}" -v "$PWD/tests":/tests "$IMG" python "/tests/lab/$TEST"

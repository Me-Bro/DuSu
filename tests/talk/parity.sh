#!/usr/bin/env bash
# Talk - "old = old" for the SERVER: the same scripted scenarios for every pre-existing mode against (1) the code before Talk, (2) the working tree with the talk switch OFF, (3) with it ON;
# then parity_compare.py proves frames, model inputs, database effects and /me equal.  Everything on scratch infrastructure (a fresh scratch MongoDB per run), no key.
#   tests/talk/parity.sh              (set TALK_BASELINE=<dir> for another "old" tree; TALK_BACKEND_DIR=<dir> for another "new" tree)
set -euo pipefail
cd "$(dirname "$0")/../.."
OLD="${TALK_BASELINE:-$PWD/tests/.baselines/lab-done/backend}"
NEW="${TALK_BACKEND_DIR:-$PWD/backend}"
rm -rf tests/talk/.out && mkdir -p tests/talk/.out
TALK_BACKEND_DIR="$OLD" TALK_ENV="TALK_LABEL=old TALK_SWITCH=none" tests/talk/run.sh parity_ws.py
TALK_BACKEND_DIR="$NEW" TALK_ENV="TALK_LABEL=new_off TALK_SWITCH=off" tests/talk/run.sh parity_ws.py
TALK_BACKEND_DIR="$NEW" TALK_ENV="TALK_LABEL=new_on TALK_SWITCH=on" tests/talk/run.sh parity_ws.py
python3 tests/talk/parity_compare.py

#!/usr/bin/env bash
# Every server-side suite against the code INSIDE a BUILT image (what a deploy runs), on a scratch MongoDB. One line per suite in tests/store/.out/baked.txt.
#   tests/store/baked_all.sh [image]          default: dusu-backend:mongo-rc1
# Besides the suites, the image's source files are proven BYTE-IDENTICAL to the tree (a sha256 over every source file).
set -uo pipefail
cd "$(dirname "$0")/../.."
IMG="${1:-dusu-backend:mongo-rc1}"
mkdir -p tests/store/.out
OUT=tests/store/.out/baked.txt; : > "$OUT"
run() {
  local name="$1"; shift
  local t0 st sum
  t0=$(date +%s)
  if "$@" > "tests/store/.out/baked_$name.log" 2>&1; then st=ok; else st=FAIL; fi
  sum=$(grep -E "[0-9]+ ?/ ?[0-9]+ checks|passed,|checks:|[0-9]+ passed" "tests/store/.out/baked_$name.log" | tail -1 | cut -c1-120)
  echo "$name $st $(( $(date +%s) - t0 ))s  $sum" | tee -a "$OUT"
}
# byte identity: the image's code == the tree
h_tree=$(cd backend && find . -type f \( -name '*.py' -o -name '*.html' -o -name '*.js' -o -name '*.txt' -o -name '*.webmanifest' -o -name '*.json' \) -not -path './.venv/*' -not -path '*/__pycache__/*' | sort | xargs sha256sum | sha256sum | cut -c1-16)
h_img=$(docker run --rm "$IMG" sh -c "cd /app && find . -type f \( -name '*.py' -o -name '*.html' -o -name '*.js' -o -name '*.txt' -o -name '*.webmanifest' -o -name '*.json' \) -not -path '*/__pycache__/*' | sort | xargs sha256sum | sha256sum | cut -c1-16")
[ "$h_tree" = "$h_img" ] && echo "identity ok - the image's source files hash to $h_img, the same as the tree" | tee -a "$OUT" || echo "identity FAIL - tree $h_tree, image $h_img" | tee -a "$OUT"
run store_unit      env STORE_BACKEND=baked STORE_TEST_IMAGE="$IMG" STORE_PG=0 tests/store/run.sh unit.py
run store_conc      env STORE_BACKEND=baked STORE_TEST_IMAGE="$IMG" STORE_PG=0 tests/store/run.sh concurrency.py
run insights_unit   env INS_BACKEND=baked INS_TEST_IMAGE="$IMG" tests/insights/run.sh unit.py
run insights_self   env INS_BACKEND=baked INS_TEST_IMAGE="$IMG" tests/insights/run.sh selftest.py
run insights_ws     env INS_BACKEND=baked INS_TEST_IMAGE="$IMG" tests/insights/run.sh ws_selftest.py
run keys_unit       env KY_BACKEND=baked KY_TEST_IMAGE="$IMG" tests/keys/run.sh unit.py
run keys_parity     env KY_BACKEND=baked KY_TEST_IMAGE="$IMG" tests/keys/run.sh parity.py
run keys_self       env KY_BACKEND=baked KY_TEST_IMAGE="$IMG" tests/keys/run.sh selftest.py
run keys_ws         env KY_BACKEND=baked KY_TEST_IMAGE="$IMG" tests/keys/run.sh ws_selftest.py
run keys_chain_unit env KY_BACKEND=baked KY_TEST_IMAGE="$IMG" tests/keys/run.sh chain_unit.py
run keys_chain_self env KY_BACKEND=baked KY_TEST_IMAGE="$IMG" tests/keys/run.sh chain_selftest.py
run keys_chain_ws   env KY_BACKEND=baked KY_TEST_IMAGE="$IMG" tests/keys/run.sh chain_ws.py
run notify_unit     env NT_BACKEND=baked NT_TEST_IMAGE="$IMG" tests/notify/run.sh unit.py
run notify_self     env NT_BACKEND=baked NT_TEST_IMAGE="$IMG" tests/notify/run.sh selftest.py
run grammar_self    env GC_BACKEND_DIR=baked GC_TEST_IMAGE="$IMG" tests/grammar/run.sh selftest.py
run grammar_ws      env GC_BACKEND_DIR=baked GC_TEST_IMAGE="$IMG" tests/grammar/run.sh ws_harness.py
run myday_unit      env MD_BACKEND=baked MD_TEST_IMAGE="$IMG" tests/my_day/run.sh unit.py
run myday_self      env MD_BACKEND=baked MD_TEST_IMAGE="$IMG" tests/my_day/run.sh selftest.py
run voice_ws        env DV_BACKEND=baked DV_TEST_IMAGE="$IMG" tests/daily_voice/run.sh ws_selftest.py
run voice_sessions  env DV_BACKEND=baked DV_TEST_IMAGE="$IMG" tests/daily_voice/run.sh ws_sessions_selftest.py
run ri_unit         env RI_BACKEND=baked RI_TEST_IMAGE="$IMG" tests/resume_interview/run.sh unit.py
run ri_self         env RI_BACKEND=baked RI_TEST_IMAGE="$IMG" tests/resume_interview/run.sh selftest.py
echo "== done" | tee -a "$OUT"

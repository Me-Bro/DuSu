#!/usr/bin/env bash
# Every browser tier against the REAL app on a scratch MongoDB (a real Chromium, the real uvicorn, the real loops), one after the other. One line per spec in
# tests/store/.out/browser.txt (full logs next to it). Long: tens of minutes. Run it in the background.
#   tests/store/browser_all.sh [name ...]      (no names = all;  names: my_day_real my_day_checks notify keys install gemini grammar ri busy lock lock2 audit)
#   BROWSER_IMAGE=dusu-backend:mongo-rc3 tests/store/browser_all.sh      runs every spec against the code INSIDE that built image (what a deploy runs)
set -uo pipefail
cd "$(dirname "$0")/../.."
if [ -n "${BROWSER_IMAGE:-}" ]; then
  export MD_BACKEND=baked MD_TEST_IMAGE="$BROWSER_IMAGE" NT_BACKEND=baked NT_TEST_IMAGE="$BROWSER_IMAGE" KY_BACKEND=baked KY_TEST_IMAGE="$BROWSER_IMAGE"
  export GC_BACKEND=baked GC_TEST_IMAGE="$BROWSER_IMAGE" RI_BACKEND=baked RI_TEST_IMAGE="$BROWSER_IMAGE" DV_BACKEND=baked DV_TEST_IMAGE="$BROWSER_IMAGE"
  export AUDIT_BACKEND=baked AUDIT_IMAGE="$BROWSER_IMAGE"
fi
mkdir -p tests/store/.out
OUT=tests/store/.out/browser.txt
WANT=("$@")
want() { [ ${#WANT[@]} -eq 0 ] && return 0; for w in "${WANT[@]}"; do [ "$w" = "$1" ] && return 0; done; return 1; }
run() {
  local name="$1"; shift
  want "$name" || return 0
  local t0 st sum
  t0=$(date +%s)
  if "$@" > "tests/store/.out/browser_$name.log" 2>&1; then st=ok; else st=FAIL; fi
  sum=$(grep -E "[0-9]+ ?/ ?[0-9]+|passed|failed|FAIL" "tests/store/.out/browser_$name.log" | grep -vE "^\s+(PASS|ok)" | tail -3 | tr '\n' ' ' | cut -c1-200)
  echo "$name $st $(( $(date +%s) - t0 ))s  $sum" | tee -a "$OUT"
}
run my_day_real   tests/my_day/browser/run_real.sh real.spec.cjs
run my_day_checks tests/my_day/browser/run_real.sh checks.spec.cjs
run notify        tests/notify/browser/run_real.sh real.spec.cjs
run keys          tests/keys/browser/run_real.sh keys.spec.cjs
run install       tests/keys/browser/run_real.sh install.spec.cjs
run gemini        tests/keys/browser/run_real.sh gemini.spec.cjs
run grammar       tests/grammar/browser/run_real.sh real.spec.cjs
run ri            tests/resume_interview/browser/run_real.sh real.spec.cjs
run busy          tests/daily_voice/browser/run_real.sh busy.spec.cjs
run lock          tests/daily_voice/browser/run_real.sh lock.spec.cjs
run lock2         tests/daily_voice/browser/run_real.sh lock2.spec.cjs
if want audit; then
  tests/audit/up.sh > tests/store/.out/browser_audit_up.log 2>&1 || { echo "audit FAIL (the audit app did not come up)" | tee -a "$OUT"; exit 1; }
  run audit tests/audit/spec.sh verify.cjs
  tests/audit/down.sh >/dev/null 2>&1 || true
fi
echo "== done" | tee -a "$OUT"

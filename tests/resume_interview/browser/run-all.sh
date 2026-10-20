#!/usr/bin/env bash
# Run every Resume Interview browser spec, one container each, and print a one-line summary per spec.
#   tests/resume_interview/browser/run-all.sh            (all)
#   tests/resume_interview/browser/run-all.sh quick      (skip the slow ones: looks, looks2, oldnew, the two "still working" cases (17 s and 18 s))
# Exit code 0 only if every spec passed. Output of each spec is kept in $OUT_DIR (default ~/.cache/dusu-ri-shots) as <spec>.log
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
OUT="${OUT_DIR:-$HOME/.cache/dusu-ri-shots}"; mkdir -p "$OUT"
ORIG="$OUT/orig-test_client.html"
# "old = old" is measured against the last commit BEFORE this feature existed (70455da), not against HEAD (which already contains it). ORIG_REV= overrides.
git -C "$REPO" show "${ORIG_REV:-70455da}:backend/test_client.html" > "$ORIG"
MODE="${1:-all}"
fail=0
run() {   # name  spec  [env assignments...]
  local name="$1" spec="$2"; shift 2
  local log="$OUT/$name.log"
  if env "$@" "$HERE/run.sh" "$spec" > "$log" 2>&1; then rc=0; else rc=$?; fi
  local line; line="$(grep -E ': [0-9]+ passed, [0-9]+ failed' "$log" | tail -1)"
  printf '%-28s %s\n' "$name" "${line:-NO SUMMARY (exit $rc) - see $log}"
  [ "$rc" -eq 0 ] || fail=1
}
run coach                coach.spec.cjs
run flow-bare-errors    flow.spec.cjs        WRAP=0
run flow-detail-errors  flow.spec.cjs        WRAP=1
run edge-bare-errors    edge.spec.cjs        WRAP=0 $( [ "$MODE" = quick ] && echo CASES=upload,job,analysis,start,answers,stt,proxy,mic,feedback,dup,finish,interrupt,links,delete,library,report,limits,recorder,storage,draft,caps,keysgate,older,recover,stuck,paused )
run edge-detail-errors  edge.spec.cjs        WRAP=1 $( [ "$MODE" = quick ] && echo CASES=upload,job,analysis,start,answers,stt,proxy,mic,feedback,dup,finish,interrupt,links,delete,library,report,limits,recorder,storage,draft,caps,keysgate,older,recover,stuck,paused )
run device              device.spec.cjs
run xss                 xss.spec.cjs
run static              static.spec.cjs
run smoke-no-auth       smoke_noauth.spec.cjs
if [ "$MODE" != quick ]; then
  run looks             looks.spec.cjs
  run looks-states      looks2.spec.cjs
  run old-equals-old    oldnew.spec.cjs      ORIG_HTML_HOST="$ORIG"
fi
exit $fail

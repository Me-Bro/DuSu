#!/usr/bin/env bash
# The existing server suites that must stay green with Talk in the tree (the working tree, on scratch infrastructure; for the baked image use tests/store/baked_all.sh).
# One line per suite in tests/talk/.out/regress.txt.     tests/talk/regress.sh
set -uo pipefail
cd "$(dirname "$0")/../.."
mkdir -p tests/talk/.out
OUT=tests/talk/.out/regress.txt; : > "$OUT"
run() {
  local name="$1"; shift
  local t0 st sum
  t0=$(date +%s)
  if "$@" > "tests/talk/.out/regress_$name.log" 2>&1; then st=ok; else st=FAIL; fi
  sum=$(grep -E "[0-9]+ ?/ ?[0-9]+ checks|passed,|checks:|[0-9]+ passed" "tests/talk/.out/regress_$name.log" | tail -1 | cut -c1-110)
  echo "$name $st $(( $(date +%s) - t0 ))s  $sum" | tee -a "$OUT"
}
run lab_server      tests/lab/run.sh selftest.py
for t in unit_forms unit_checker unit_explain unit_bank; do run "lab_$t" python3 tests/lab/$t.py; done
run lab_lint        python3 tests/lab/lint_bank.py
run keys_unit       tests/keys/run.sh unit.py
run keys_parity     tests/keys/run.sh parity.py
run keys_selftest   tests/keys/run.sh selftest.py
run keys_ws         tests/keys/run.sh ws_selftest.py
run keys_chain_unit tests/keys/run.sh chain_unit.py
run keys_chain_self tests/keys/run.sh chain_selftest.py
run keys_chain_ws   tests/keys/run.sh chain_ws.py
run voice_ws        tests/daily_voice/run.sh ws_selftest.py
run voice_sessions  tests/daily_voice/run.sh ws_sessions_selftest.py
run grammar_self    tests/grammar/run.sh selftest.py
run grammar_ws      tests/grammar/run.sh ws_harness.py
run notify_unit     tests/notify/run.sh unit.py
run notify_self     tests/notify/run.sh selftest.py
run myday_unit      tests/my_day/run.sh unit.py
run myday_self      tests/my_day/run.sh selftest.py
run ri_unit         tests/resume_interview/run.sh unit.py
run ri_self         tests/resume_interview/run.sh selftest.py
run insights_unit   tests/insights/run.sh unit.py
run insights_self   tests/insights/run.sh selftest.py
run insights_ws     tests/insights/run.sh ws_selftest.py
run talk_unit_topics python3 tests/talk/unit_topics.py
run talk_unit_reply  python3 tests/talk/unit_reply.py
run talk_unit_engine tests/talk/run.sh --nomongo unit_engine.py
run talk_http        tests/talk/run.sh selftest.py
run talk_ws          tests/talk/run.sh ws_selftest.py
echo "== done" | tee -a "$OUT"

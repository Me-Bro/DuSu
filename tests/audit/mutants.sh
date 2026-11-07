#!/usr/bin/env bash
# Planted bugs for the client side of the audit fixes (tests/audit/mutants.py): each broken copy of the page is served to the verification sections that must catch it.
# Every one must make verify.cjs FAIL. Needs the audit app up (tests/audit/up.sh) and, for the sections it runs, the scratch database in its seeded state.
#   tests/audit/mutants.sh                  all            tests/audit/mutants.sh m03_deeplink_never_waits m10_lang_pill_back_at_bottom      only these
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
LIST="$(python3 "$HERE/mutants.py" "$@")" || { echo "$LIST"; exit 2; }
caught=0; total=0; missed=()
while IFS= read -r line; do
  [ -z "$line" ] && continue
  name="${line%% *}"; rest="${line#* }"; sections="${rest%% ::*}"; why="${rest#*:: }"
  total=$((total+1))
  out="$(AUD_ENV="ONLY=$sections HTML_OVERRIDE=/repo/tests/audit/.out/mut/$name.html" bash "$HERE/spec.sh" verify.cjs 2>&1)"; rc=$?
  nfail="$(echo "$out" | grep -c '^  FAIL')"
  if [[ "$name" == ctl_* ]]; then            # a control: nothing is broken, so everything must pass
    if [ $rc -eq 0 ] && [ "$nfail" -eq 0 ]; then caught=$((caught+1)); echo "OK      $name  [$sections]  all checks pass  - $why"
    else missed+=("$name"); echo "BROKEN  $name  [$sections]  rc=$rc  $nfail failing check(s) - $why"; fi
  elif [ $rc -ne 0 ] && [ "$nfail" -gt 0 ]; then caught=$((caught+1)); echo "CAUGHT  $name  [$sections]  $nfail failing check(s)  - $why"
  else missed+=("$name"); echo "MISSED  $name  [$sections]  rc=$rc  - $why"; fi
done <<< "$LIST"
echo; echo "$caught of $total as expected (planted bugs caught, controls clean)"
[ "$caught" -eq "$total" ] || { echo "NOT CAUGHT: ${missed[*]}"; exit 1; }

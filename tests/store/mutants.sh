#!/usr/bin/env bash
# Do the store tests catch a planted bug?  One deliberate bug at a time in a COPY of the layer (tests/store/mutants.py); the first tier that fails catches it.
# Usage: tests/store/mutants.sh [S1 S5 ...]      (no ids = all)       results: tests/store/.out/mutants.txt
set -uo pipefail
cd "$(dirname "$0")/../.."
mkdir -p tests/store/.out
IDS=("$@"); [ ${#IDS[@]} -eq 0 ] && IDS=($(python3 tests/store/mutants.py --ids))
python3 tests/store/mutants.py --check || exit 1
OUT=tests/store/.out/mutants.txt; : > "$OUT"
caught=0; survived=0
for id in "${IDS[@]}"; do
  rm -rf tests/store/.mutants; mkdir -p tests/store/.mutants/backend
  cp -r backend/app tests/store/.mutants/backend/app
  python3 tests/store/mutants.py --apply "$id" tests/store/.mutants/backend/app || { echo "$id PATCH FAILED" | tee -a "$OUT"; continue; }
  desc=$(python3 tests/store/mutants.py --desc "$id"); by=""
  for tier in "unit.py" "concurrency.py" "differential.py 11 250"; do
    pg=0; case "$tier" in differential*) pg=1 ;; esac
    if ! STORE_BACKEND="$PWD/tests/store/.mutants/backend" STORE_PG=$pg timeout 250 tests/store/run.sh $tier >/dev/null 2>&1; then by="${tier%% *}"; break; fi
  done
  if [ -n "$by" ]; then caught=$((caught+1)); echo "$id CAUGHT by $by - $desc" | tee -a "$OUT"; else survived=$((survived+1)); echo "$id SURVIVED - $desc" | tee -a "$OUT"; fi
done
rm -rf tests/store/.mutants
echo "== $caught caught, $survived survived of ${#IDS[@]}" | tee -a "$OUT"

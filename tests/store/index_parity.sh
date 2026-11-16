#!/usr/bin/env bash
# No index lost in the translation: every index (and unique constraint, and primary key) the OLD SQLAlchemy models declare must exist in the NEW store models, with the
# same columns / uniqueness / partial-ness. Extras on the new side are listed. Needs the test image (it has SQLAlchemy for the old tree) and tests/store/.old/backend.
set -euo pipefail
cd "$(dirname "$0")/../.."
IMG="${STORE_TEST_IMAGE:-dusu-mongo-test}"
OLD="$PWD/tests/store/.old/backend"; NEW="${STORE_BACKEND:-$PWD/backend}"
[ -d "$OLD" ] || { echo "missing $OLD (git archive of the commit before the migration)"; exit 2; }
mkdir -p tests/store/.out
for side in old new; do
  d=$OLD; [ "$side" = new ] && d=$NEW
  docker run --rm -e SESSION_SECRET=x -v "$d":/app:ro -v "$PWD/tests":/tests:ro "$IMG" python /tests/store/index_dump.py > "tests/store/.out/idx_$side.json"
done
python3 - <<'PY'
import json, sys
old = json.load(open("tests/store/.out/idx_old.json")); new = json.load(open("tests/store/.out/idx_new.json"))
def norm(e):
    return (e["table"], tuple(e["cols"]), bool(e["unique"]))
N = {norm(e): e for e in new}
bad = []
for e in old:
    k = norm(e)
    if e.get("pk"):
        ok = (e["table"], tuple(e["cols"]), True) in N or len(e["cols"]) == 1       # a single-column pk is the document's _id
    else:
        ok = k in N
    if not ok:
        bad.append(e)
    elif not e.get("pk") and k in N and bool(N[k]["partial"]) != bool(e["partial"]):
        bad.append({**e, "problem": f"partial-ness differs (old {e['partial']}, new {N[k]['partial']})"})
O = {norm(e) for e in old}
extra = [e for e in new if norm(e) not in O]
print(f"old tree: {len(old)} index/constraint/pk entries on {len({e['table'] for e in old})} tables | new tree: {len(new)} entries on {len({e['table'] for e in new})} collections")
print(f"LOST in the translation: {len(bad)}")
for e in bad:
    print("   ", e)
print(f"extra on the new side: {len(extra)}")
for e in extra:
    print("   +", e["table"], e["cols"], "unique" if e["unique"] else "", "partial" if e["partial"] else "", e.get("name"))
sys.exit(1 if bad else 0)
PY

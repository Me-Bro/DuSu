"""Compare two golden outputs (old = Postgres, new = Mongo): every recorded call and every table row. python3 golden_diff.py old.json new.json"""

import json
import sys

a = json.load(open(sys.argv[1]))
b = json.load(open(sys.argv[2]))
bad = 0


def show(label, x, y):
    global bad
    bad += 1
    if bad <= 25:
        print(f"\nDIFFERENT {label}\n  old: {json.dumps(x, sort_keys=True, default=str)[:700]}\n  new: {json.dumps(y, sort_keys=True, default=str)[:700]}")


ca, cb = a["calls"], b["calls"]
if len(ca) != len(cb):
    show("number of recorded calls", len(ca), len(cb))
for (la, va), (lb, vb) in zip(ca, cb):
    if la != lb:
        show("call labels diverged", la, lb)
        break
    if va != vb:
        show("call: " + la, va, vb)
ta, tb = a["tables"], b["tables"]
for t in sorted(set(ta) | set(tb)):
    ra, rb = ta.get(t), tb.get(t)
    if ra == rb:
        continue
    if ra is None or rb is None:
        show(f"table {t} exists on one side only", ra is not None, rb is not None)
        continue
    if len(ra) != len(rb):
        show(f"table {t}: row count", len(ra), len(rb))
    for i, (x, y) in enumerate(zip(ra, rb)):
        if x != y:
            diff = {k: (x.get(k), y.get(k)) for k in set(x) | set(y) if x.get(k) != y.get(k)}
            show(f"table {t} row {i}", {k: v[0] for k, v in diff.items()}, {k: v[1] for k, v in diff.items()})
            break

n_calls = len(ca)
n_rows = sum(len(v) for v in ta.values())
print(f"\n{n_calls} calls and {n_rows} table rows compared: " + ("IDENTICAL" if not bad else f"{bad} difference(s)"))
sys.exit(1 if bad else 0)

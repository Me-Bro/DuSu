"""Compare two shadow outputs (old = Postgres, new = Mongo). python3 shadow_diff.py old.json new.json   Prints WHICH endpoint differs and the keys that differ - never a value."""

import json
import sys

a, b = json.load(open(sys.argv[1])), json.load(open(sys.argv[2]))
bad = 0


def keydiff(x, y, path=""):
    if isinstance(x, dict) and isinstance(y, dict):
        out = []
        for k in sorted(set(x) | set(y)):
            if k not in x or k not in y:
                out.append(f"{path}/{k} (only on the {'old' if k in x else 'new'} side)")
            else:
                out += keydiff(x[k], y[k], f"{path}/{k}")
        return out
    if isinstance(x, list) and isinstance(y, list):
        if len(x) != len(y):
            return [f"{path} (list length {len(x)} vs {len(y)})"]
        out = []
        for i, (p, q) in enumerate(zip(x, y)):
            out += keydiff(p, q, f"{path}[{i}]")
        return out
    return [] if x == y else [f"{path} ({type(x).__name__} vs {type(y).__name__})" if type(x) is not type(y) else path]


if a["users"] != b["users"]:
    print("different learners:", len(a["users"]), "vs", len(b["users"]))
    bad += 1
A, B = a["answers"], b["answers"]
for k in sorted(set(A) | set(B)):
    if k not in A or k not in B:
        print("only on one side:", k)
        bad += 1
        continue
    if A[k] != B[k]:
        bad += 1
        if bad <= 30:
            d = keydiff(A[k], B[k])
            print(f"DIFFERENT {k}: status {A[k].get('status')} vs {B[k].get('status')}; differing keys: {d[:6]}")
print(f"\n{len(A)} answers for {len(a['users'])} learner(s) compared: " + ("IDENTICAL" if not bad else f"{bad} difference(s)"))
sys.exit(1 if bad else 0)

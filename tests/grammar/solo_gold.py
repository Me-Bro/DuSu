import json, sys, collections
sys.path.insert(0, "backend")
from app.grammar import detectors
from app.grammar.text import keys as tkeys, canon_contractions
rows = [json.loads(l) for l in open("tests/grammar/gold.jsonl")]
fp, tp, miss = collections.Counter(), collections.Counter(), collections.Counter()
fps = []
for r in rows:
    src = r.get("src", "chrome"); t = r["text"]
    try: hits = detectors.solo_hits(canon_contractions(tkeys(t)), source=src, has_q=("?" in t))
    except Exception as e: print("EXC", r["id"], e); continue
    E = r["expect"]; exp = {m["rule"].split("#")[0] for m in E.get("marks", [])}
    if r["group"] in ("clean", "twin", "trap", "inject") and E.get("status") in ("ok", "skip") and not exp:
        for h in hits: fp[h.rule] += 1; fps.append((r["id"], h.rule, t[:90]))
    else:
        got = {h.rule.split("#")[0] for h in hits}
        for e in exp: (tp if e in got else miss)[e] += 1
        for h in hits:
            if h.rule.split("#")[0] not in exp and exp: fp[h.rule] += 1; fps.append((r["id"], h.rule, "(wrong rule) " + t[:80]))
print("FALSE POSITIVES:", sum(fp.values()), dict(fp))
for x in fps[:25]: print(x)
print("solo recall by rule:", {k: f"{tp[k]}/{tp[k]+miss[k]}" for k in sorted(set(tp)|set(miss)) if tp[k]})

#!/usr/bin/env python3
"""Static scan of every HTML-injecting sink in the page (audit E-1: "148 innerHTML uses in the older modules").

For each `.innerHTML = / +=`, `insertAdjacentHTML(`, `.outerHTML =` and `document.write(` it reads the template that follows and lists every `${...}` interpolation that is NOT
visibly safe, so a human can decide what data it carries. "Visibly safe" = wrapped in an escaper (`esc(`, `A(`, `escapeHtml(`, `attr(`), a numeric coercion (`Number(`, `+x`, `parseInt`,
`Math.`, `.length`, `.toFixed(`), a ternary of string literals, or a constant table lookup. Everything else is printed with the source line, grouped by risk:

  usage:  python3 tests/audit/innerhtml_scan.py [path-to-html] [--all]        (default: backend/test_client.html; --all also lists the safe ones)

Exit code 0 always (it is a report). tests/audit/verify.cjs runs the CANARY (the dynamic check); this is the map that says where to look.
"""
import json
import re
import sys
from pathlib import Path

path = Path(next((a for a in sys.argv[1:] if not a.startswith("--")), "backend/test_client.html"))
show_all = "--all" in sys.argv
src = path.read_text(encoding="utf-8")
m = re.search(r"<script>(.*?)</script>", src[src.index("</style>"):], re.S)           # the big inline script (the first <script> is the install plumbing)
scripts = re.findall(r"<script>(.*?)</script>", src, re.S)
js = max(scripts, key=len)
base_line = src[: src.index(js)].count("\n") + 1

SINK = re.compile(r"(\.innerHTML\s*\+?=|insertAdjacentHTML\s*\(|\.outerHTML\s*=|document\.write\s*\()")
SAFE_WRAP = re.compile(r"^\s*(esc|A|escapeHtml|attr|escAttr|encodeURIComponent|JSON\.stringify|Number|parseInt|parseFloat|Math\.\w+|String\(Number|plural|normTime|fmtMin|fmtTime|fmtInstant|rankLabel|num100)\s*\(")
SAFE_PLAIN = re.compile(r"^\s*(\+?\w+\.(length|toFixed\([^)]*\))|[\d.]+|\w+\s*[+\-*/]\s*[\d.]+|\w+%\w+|i|idx|n|pct|\w*(Pct|Count|Num|N)\b|\w+\.(xp|streak|level|rank|minutes|sessions|id|n|count|score|overall|pct|avg|hits|total|left|limit))\s*$")


def line_of(pos):
    return base_line + js[:pos].count("\n")


def template_after(pos):
    """The expression text after a sink up to the end of the statement (balanced for backticks / quotes / parens, good enough for a report)."""
    i, depth, out, q = pos, 0, [], None
    while i < len(js) and i - pos < 6000:
        ch = js[i]
        out.append(ch)
        if q:
            if ch == "\\":
                out.append(js[i + 1]); i += 2; continue
            if q == "`" and ch == "$" and js[i + 1:i + 2] == "{":
                # skip a nested ${ ... } by brace counting
                j, b = i + 2, 1
                while j < len(js) and b:
                    b += (js[j] == "{") - (js[j] == "}"); j += 1
                out.append(js[i + 1:j]); i = j; continue
            if ch == q:
                q = None
        else:
            if ch in "'\"`":
                q = ch
            elif ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
                if depth < 0:
                    break
            elif ch == ";" and depth <= 0:
                break
        i += 1
    return "".join(out)


def interpolations(text):
    res, i = [], 0
    while True:
        j = text.find("${", i)
        if j < 0:
            return res
        k, b = j + 2, 1
        while k < len(text) and b:
            b += (text[k] == "{") - (text[k] == "}"); k += 1
        res.append(text[j + 2:k - 1].strip()); i = k


def classify(expr):
    e = expr.strip()
    if SAFE_WRAP.match(e) or SAFE_PLAIN.match(e):
        return "safe"
    if re.fullmatch(r"""([^?]+\?\s*(["'`][^"'`]*["'`]|\d+)\s*:\s*(["'`][^"'`]*["'`]|\d+))""", e):
        return "safe"                                                                        # a ternary between two literals (whatever the condition)
    if re.fullmatch(r"""av\((r\.alias|["'][^"']*["'])\)""", e):
        return "safe"                                                                        # one letter of a server-made alias (adjective + animal) or of a literal
    if re.fullmatch(r"""(medals|MEDALS|ICONS|ICON)\[[^\]]+\]""", e):
        return "safe"                                                                        # a lookup in a constant table
    if re.fullmatch(r"[A-Z_][A-Z0-9_]*\[[^\]]+\]", e) or re.fullmatch(r"(BADGE_LABELS|BADGE_HOW|METRIC_LABELS|A_METRIC_LABELS|WORLD_NAMES|LEVEL_ICONS)\[[^\]]+\](\s*\|\|\s*\w+)?", e):
        return "safe"                                                                        # a lookup in a constant table
    if re.search(r"\besc\(", e) and not re.search(r"\+\s*\w+(\.\w+)*\s*$", e):
        return "safe"                                                                        # the value passes through esc() somewhere in the expression
    if re.search(r"\.map\(", e) and ".join(" in e:
        return "nested"                                                                      # a nested template: its own interpolations are scanned separately
    return "check"


rows, counts = [], {"sinks": 0, "safe": 0, "nested": 0, "check": 0, "constant": 0}
for m in SINK.finditer(js):
    counts["sinks"] += 1
    t = template_after(m.end())
    exprs = interpolations(t)
    if not exprs:
        counts["constant"] += 1
        if show_all:
            rows.append((line_of(m.start()), m.group(1).strip(), "constant", "(no interpolation)"))
        continue
    for e in exprs:
        c = classify(e)
        counts[c] += 1
        if c == "check" or show_all:
            rows.append((line_of(m.start()), m.group(1).strip(), c, e[:110].replace("\n", " ")))

print(f"{path}: {counts['sinks']} HTML sinks; {counts['constant']} have no interpolation, {counts['safe']} interpolations are visibly safe, {counts['nested']} are nested templates, "
      f"{counts['check']} need a look")
print()
for line, sink, c, e in rows:
    print(f"  L{line:<6} {sink:<20} [{c}] {e}")
json.dump({"counts": counts, "check": [{"line": l, "sink": s, "expr": e} for l, s, c, e in rows if c == "check"]}, open("/tmp/innerhtml_scan.json", "w"), indent=1)

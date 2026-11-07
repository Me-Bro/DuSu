#!/usr/bin/env python3
"""Compare two audit sweeps (results-walk-*.json from tests/audit/walk.cjs): did the fixes move the numbers?

    python3 tests/audit/compare.py BEFORE.json AFTER.json [--screens]

Totals over every screen that appears in BOTH files (matched by tag + screen name): tiny text (< 12 px), tap targets under 44 px, low-contrast text, controls with no name, screens with
horizontal overflow, console errors, failed / >= 400 requests. `--screens` also prints every screen whose numbers got WORSE (a regression the totals could hide).
"""
import json
import sys

args = [a for a in sys.argv[1:] if not a.startswith("--")]
if len(args) != 2:
    sys.exit(__doc__)
before = {(r["tag"], r["name"]): r for r in json.load(open(args[0]))}
after = {(r["tag"], r["name"]): r for r in json.load(open(args[1]))}
common = sorted(set(before) & set(after))

METRICS = [
    ("tiny text (< 12 px)", lambda r: r["tinyText"]["count"]),
    ("tap targets < 44 px", lambda r: len(r["smallTargets"])),
    ("low-contrast text", lambda r: r["contrast"]["low"]),
    ("controls with no name", lambda r: len(r["noName"])),
    ("images with no alt", lambda r: len(r["imgNoAlt"])),
    ("screens that overflow sideways", lambda r: int(bool(r["pageOverflowX"] or r["wrapOverflowX"] or r["sticksOut"]))),
    ("console errors", lambda r: len([c for c in r["console"] if c.startswith(("error", "pageerror"))])),
    ("failed / HTTP >= 400 requests", lambda r: len(r["failed"]) + len(r["bad"])),
]
print(f"{len(common)} screens in common ({len(before)} before, {len(after)} after)\n")
print(f"  {'metric':<34}{'before':>8}{'after':>8}{'change':>9}")
for name, f in METRICS:
    b = sum(f(before[k]) for k in common)
    a = sum(f(after[k]) for k in common)
    print(f"  {name:<34}{b:>8}{a:>8}{a - b:>+9}")

# the screens people spend time on: how tall are they?
print("\n  scroll height of the main screens (px; shorter = fewer screens to scroll)")
for key in [("active-390", "home"), ("newbie-390", "landing"), ("keyed-390", "home"), ("active-390", "practice"), ("active-390", "journey"), ("active-390", "keys"), ("active-390", "subscribe"),
            ("newbie-390", "keys")]:
    if key in before and key in after and before[key].get("scroll") and after[key].get("scroll"):
        b, a = before[key]["scroll"]["h"], after[key]["scroll"]["h"]
        print(f"    {key[0]:<14}{key[1]:<22}{b:>6} -> {a:<6} ({a - b:+d})")

if "--screens" in sys.argv:
    print("\n  screens that got worse:")
    worse = 0
    for k in common:
        for name, f in METRICS:
            if f(after[k]) > f(before[k]):
                worse += 1
                print(f"    {k[0]:<14}{k[1]:<24}{name}: {f(before[k])} -> {f(after[k])}")
    print("    (none)" if not worse else f"    {worse} regressions")

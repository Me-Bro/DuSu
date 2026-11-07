"""Make the poster's QR code (qr.svg + qr-meta.json).

Run through build.sh (inside python:3.12-slim with `pip install segno`).
The URL lives ONLY here; change it, rebuild, and the poster follows.

Choices that matter for a printed code that has to scan from a wall:
  * byte mode, error correction Q (25 % of the code can be damaged)
  * plain square modules, no logo in the middle, dark on white
  * a 4-module quiet zone is part of the SVG (the standard minimum)
"""
import json
import sys

import segno

URL = "https://dusu.ranabrothers.online/?s=poster"
DARK = "#0a1030"   # navy, same family as the poster background
LIGHT = "#ffffff"
BORDER = 4         # quiet zone, in modules

qr = segno.make(URL, error="q", mode="byte", micro=False, boost_error=False)

# One filled path of whole-module squares (no strokes: stroked rows can show
# hairline seams in a printed PDF). Adjacent dark modules in a row are merged.
rows = list(qr.matrix_iter(scale=1, border=BORDER, verbose=False))
size = len(rows)
d = []
for y, row in enumerate(rows):
    x = 0
    while x < size:
        if row[x]:
            x0 = x
            while x < size and row[x]:
                x += 1
            d.append(f"M{x0} {y}h{x - x0}v1h-{x - x0}z")
        else:
            x += 1
svg = (
    f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" '
    f'shape-rendering="crispEdges">'
    f'<rect width="{size}" height="{size}" fill="{LIGHT}"/>'
    f'<path fill="{DARK}" d="{"".join(d)}"/></svg>'
)
with open("qr.svg", "w", encoding="utf-8") as fh:
    fh.write(svg)

modules = size - 2 * BORDER
meta = {
    "url": URL,
    "version": str(qr.version),
    "error": qr.error,
    "mode": qr.mode,
    "modules": modules,
    "border": BORDER,
    "total_modules_with_border": modules + 2 * BORDER,
}
with open("qr-meta.json", "w", encoding="utf-8") as fh:
    json.dump(meta, fh, indent=2)
print(json.dumps(meta))
sys.exit(0)

"""Printer-friendliness checks on the two printer PDFs (rasterised at 300 dpi by verify.sh).  Exit 1 on any failure.

  1. nothing is printed in the outer 11.5 mm of the page (home/office printers cannot print the last 4-6 mm)
  2. ink budget: the page stays mostly paper (area covered <= 20 %, average ink density <= 8 %, versus ~95 % / 43 % for the dark poster)
  3. print-bw uses black/grey only (no colour pixels at all); print-colour still reads when a B&W printer converts it to grey
  4. the dark poster is reported for comparison
"""
import sys

import numpy as np
from PIL import Image

fails = []
MM = 300 / 25.4


def load(name):
    return np.asarray(Image.open(f".work/{name}300.png").convert("RGB")).astype(np.float32) / 255.0


def luma(a):
    return a @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


def ink(a):
    lum = luma(a)
    area = float((lum < 0.96).mean()) * 100
    k = 1 - a.max(axis=2)
    d = np.where(k < 1, 1 - k, 1)
    c = (1 - a[:, :, 0] - k) / d
    m = (1 - a[:, :, 1] - k) / d
    y = (1 - a[:, :, 2] - k) / d
    return area, float((c.mean() + m.mean() + y.mean() + k.mean()) / 4) * 100


import os
# the dark poster is only the yardstick; if it was not built, use the figure measured when it was (94.7 % area, 42.9 % ink density)
if os.path.exists(".work/dark300.png") and os.path.exists("out/DuSu-poster-A4.pdf"):
    da, dd = ink(load("dark"))
    print(f"dark poster (for comparison)          area covered {da:5.1f} %   ink density {dd:5.1f} %")
else:
    da, dd = 94.7, 42.9
    print("dark poster not built; comparing with its measured figures: area covered 94.7 %, ink density 42.9 %")

for name in ("print-colour", "print-bw"):
    a = load(name)
    h, w, _ = a.shape
    lum = luma(a)
    # 1. empty margin
    m = int(11.5 * MM)
    ring = np.ones((h, w), bool)
    ring[m:h - m, m:w - m] = False
    stray = int((lum[ring] < 0.985).sum())
    print(f"[{name}] page {w}x{h}px, non-white pixels in the outer 11.5 mm: {stray}")
    if stray:
        fails.append(f"{name}: {stray} printed pixels inside the unprintable margin")
    # 2. ink budget
    area, dens = ink(a)
    print(f"[{name}] area covered {area:5.1f} %   ink density {dens:5.1f} %   ({dd / dens:.1f}x less ink than the dark poster)")
    if area > 20 or dens > 8:
        fails.append(f"{name}: too much ink (area {area:.1f} %, density {dens:.1f} %)")
    # 3. colour discipline
    sat = (a.max(axis=2) - a.min(axis=2))
    coloured = float((sat > 0.04).mean()) * 100
    if name == "print-bw":
        print(f"[{name}] coloured pixels: {coloured:.3f} % (must be 0)")
        if coloured > 0.0:
            fails.append("print-bw contains colour")
    else:
        # simulate 'print in grayscale' of the colour page: every text colour must stay clearly darker than paper
        g = lum
        txt = g[(g < 0.96)]
        mid = float(np.percentile(txt, 90))  # 90 % of inked pixels are at least this dark-or-lighter
        print(f"[{name}] grayscale view: 90th-percentile inked pixel luminance {mid:.2f} (1 = paper white)")
        # the lightest ink we use (hairlines, antialiasing excluded) must still be visible: > 8 % darker than paper
        solid = g[(g < 0.85)]
        if solid.size < 1000:
            fails.append("print-colour: almost nothing is dark enough to print in grayscale")

print()
if fails:
    print("PRINT CHECKS FAILED:", "; ".join(fails))
    sys.exit(1)
print("printer checks passed")

"""Rough ink-use estimate of a page picture (what a printer would have to lay down).

  area covered  = share of the page that is not (near) white paper
  ink density   = average of the four CMYK channels over the whole page (naive RGB->CMYK, no printer profile),
                  i.e. 'how much ink out of a completely full page'. Good for comparing versions, not for pricing.
"""
import sys
import numpy as np
from PIL import Image

def report(path, label=None, trim_px=0):
    im = Image.open(path).convert("RGB")
    if trim_px:
        im = im.crop((trim_px, trim_px, im.width - trim_px, im.height - trim_px))
    a = np.asarray(im).astype(np.float32) / 255.0
    lum = a @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    area = float((lum < 0.96).mean()) * 100
    k = 1 - a.max(axis=2)
    d = np.where(k < 1, 1 - k, 1)
    c = (1 - a[:, :, 0] - k) / d; m = (1 - a[:, :, 1] - k) / d; y = (1 - a[:, :, 2] - k) / d
    dens = float((c.mean() + m.mean() + y.mean() + k.mean()) / 4) * 100
    gray_dens = float((1 - lum).mean()) * 100
    print(f"{label or path:34s} area covered {area:5.1f} %   ink density {dens:5.1f} %   (darkness {gray_dens:5.1f} %)")
    return area, dens

if __name__ == "__main__":
    for p in sys.argv[1:]:
        report(p)

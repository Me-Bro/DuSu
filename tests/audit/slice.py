"""Cut a tall screenshot into slices of at most H pixels (default 1500) so each one can be read at full size: slice.py <png> [H]. Writes <png-stem>__s1.png, __s2.png ..."""
import sys
from PIL import Image
p = sys.argv[1]; H = int(sys.argv[2]) if len(sys.argv) > 2 else 1500
im = Image.open(p); w, h = im.size
n = 0
for y in range(0, h, H):
    n += 1
    im.crop((0, y, w, min(h, y + H))).save(p[:-4] + f"__s{n}.png")
print(n, "slices from", p, im.size)

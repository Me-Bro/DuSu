"""Web icons for the installed web app (PWA), cut from the same master art as the Android icons (icon-master.png, the gold D-mark on navy).

The manifest used to point 192 / 512 / "maskable" at ONE 1254 px, 1.7 MB logo (not maskable-safe: its rounded-square corners are transparent, so a maskable crop
showed black corners; and every install, favicon and home-screen icon downloaded 1.7 MB). This writes small, correctly-sized files with VERSIONED names into
backend/assets/icons/ (`/assets/` is cache-first in the service worker, so a changed icon needs a new file name, never the same one):

    dusu-192-v1.png            192x192  purpose "any"      the art as drawn (rounded square, transparent corners)
    dusu-512-v1.png            512x512  purpose "any"
    dusu-maskable-512-v1.png   512x512  purpose "maskable" full-bleed navy, the art at 90% so the wordmark sits inside the 80% safe circle
    apple-touch-180-v1.png     180x180  opaque (iOS paints transparency black)
    badge-96-v1.png            96x96    white-on-transparent silhouette for the push `badge` (copied from the TWA's notification icon)

Run:  python3 android-twa/gen_web_icons.py        (needs Pillow; bump the -v1 suffix here AND in manifest.webmanifest / sw.js / test_client.html when the art changes)
"""

import os
import shutil

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "backend", "assets", "icons")
SRC = Image.open(os.path.join(HERE, "icon-master.png")).convert("RGBA")
V = "v1"
os.makedirs(OUT, exist_ok=True)


def save(img, name):
    p = os.path.join(OUT, name)
    img.save(p, optimize=True)
    print(f"{name}: {img.size[0]}x{img.size[1]}, {os.path.getsize(p) // 1024} KB")


def gradient(size, top=(6, 52, 150), bottom=(8, 74, 224)):
    """The navy the art's own edges fade to (sampled from icon-master.png), so a full-bleed background is seamless."""
    g = Image.new("RGBA", (size, size))
    px = g.load()
    for y in range(size):
        t = y / (size - 1)
        c = tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3)) + (255,)
        for x in range(size):
            px[x, y] = c
    return g


def fit(size, scale):
    art = SRC.resize((round(size * scale), round(size * scale)), Image.LANCZOS)
    canvas = gradient(size)
    off = (size - art.size[0]) // 2
    canvas.alpha_composite(art, (off, off))
    return canvas


save(SRC.resize((192, 192), Image.LANCZOS), f"dusu-192-{V}.png")
save(SRC.resize((512, 512), Image.LANCZOS), f"dusu-512-{V}.png")
save(fit(512, 0.90), f"dusu-maskable-512-{V}.png")
save(fit(180, 0.96).convert("RGB"), f"apple-touch-180-{V}.png")
shutil.copyfile(os.path.join(HERE, "app", "src", "main", "res", "drawable-xxxhdpi", "ic_notification_icon.png"), os.path.join(OUT, f"badge-96-{V}.png"))
print(f"badge-96-{V}.png: copied from the TWA's notification icon")

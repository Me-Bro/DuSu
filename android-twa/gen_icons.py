"""Generate DuSu app icons from Logo.png (the gold D-mark) into android-twa res dirs.
Run: backend/.venv/Scripts/python.exe android-twa/gen_icons.py
"""
import os
from PIL import Image

ROOT = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(ROOT, "app", "src", "main", "res")
MASTER = os.path.join(ROOT, "icon-master.png")

src = Image.open(MASTER).convert("RGBA")

# icon-master.png's opaque content fills ~97% of its own canvas edge-to-edge (no
# built-in padding). Pasted at full size, the mark reads as oversized and gets
# clipped by round/squircle launcher masks. Inset it onto a transparent canvas
# instead of resizing to fill.
LEGACY_SAFE = 0.82   # legacy launcher icons: modest margin so round masks don't clip it
FG_SAFE = 0.66       # Android adaptive-icon safe zone: content must fit the inner ~72dp of the 108dp canvas

# Legacy launcher icons (square + round use the same designed art; device masks it).
LEGACY = {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}
# Adaptive foreground layers are 108dp canvases.
FG = {"mdpi": 108, "hdpi": 162, "xhdpi": 216, "xxhdpi": 324, "xxxhdpi": 432}

def save(img, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path, "PNG")

def inset(px, safe_zone):
    """Resize src to fit `safe_zone` fraction of a px*px canvas, centered, transparent margin."""
    content_px = round(px * safe_zone)
    content = src.resize((content_px, content_px), Image.LANCZOS)
    canvas = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    offset = (px - content_px) // 2
    canvas.paste(content, (offset, offset), content)
    return canvas

for dpi, px in LEGACY.items():
    im = inset(px, LEGACY_SAFE)
    save(im, os.path.join(RES, f"mipmap-{dpi}", "ic_launcher.png"))
    save(im, os.path.join(RES, f"mipmap-{dpi}", "ic_launcher_round.png"))

for dpi, px in FG.items():
    im = inset(px, FG_SAFE)
    save(im, os.path.join(RES, f"mipmap-{dpi}", "ic_launcher_foreground.png"))

# Splash / in-app logo (keep the existing filename the layout references).
save(src.resize((512, 512), Image.LANCZOS),
     os.path.join(RES, "drawable", "dusu_logo.png"))

# Play Store 512 icon (kept in repo for the listing).
save(src.resize((512, 512), Image.LANCZOS), os.path.join(ROOT, "play-icon-512.png"))

print("icons generated OK")

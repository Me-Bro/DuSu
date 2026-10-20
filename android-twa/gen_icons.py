"""Generate DuSu app icons from Logo.png (the gold D-mark) into android-twa res dirs.
Run: backend/.venv/Scripts/python.exe android-twa/gen_icons.py
"""
import os
from PIL import Image

ROOT = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(ROOT, "app", "src", "main", "res")
MASTER = os.path.join(ROOT, "icon-master.png")

src = Image.open(MASTER).convert("RGBA")


def notification_icons():
    """Status-bar small icon: Android draws ONLY the alpha channel, so a coloured launcher icon turns into a grey square.
    Builds a white-on-transparent silhouette of the D-mark (bubble + face + sound bars) from icon-master.png:
    threshold the mark's brightness against its dark navy interior, fill tiny enclosed holes left by the gradient,
    then punch the three bubble dots out as clean round holes. Needs numpy (only for this one step)."""
    from collections import deque
    import numpy as np
    from PIL import ImageDraw, ImageFilter

    crop = src.convert("RGB").crop((200, 100, 1020, 720))            # the D-mark only: no wordmark, tagline or edge glow
    a = np.asarray(crop).astype(float)
    lum = 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]
    mask = (lum > 70).astype(np.uint8) * 255
    mask[:60, 735:] = 0                                              # glow speckle outside the D's top-right curve
    im = Image.fromarray(mask).filter(ImageFilter.MedianFilter(11))

    m = np.asarray(im) > 127                                         # fill small enclosed dark holes (area < 6000 px)
    h, w = m.shape
    seen = np.zeros((h, w), bool)
    for y in range(h):
        for x in range(w):
            if m[y, x] or seen[y, x]:
                continue
            q, comp, touches_edge = deque([(y, x)]), [], False
            seen[y, x] = True
            while q:
                cy, cx = q.popleft()
                comp.append((cy, cx))
                if cy in (0, h - 1) or cx in (0, w - 1):
                    touches_edge = True
                for ny, nx in ((cy + 1, cx), (cy - 1, cx), (cy, cx + 1), (cy, cx - 1)):
                    if 0 <= ny < h and 0 <= nx < w and not m[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        q.append((ny, nx))
            if not touches_edge and len(comp) < 6000:
                for cy, cx in comp:
                    m[cy, cx] = True
    im = Image.fromarray(m.astype(np.uint8) * 255)
    d = ImageDraw.Draw(im)
    for cx in (148, 220, 292):                                       # the bubble's three dots
        d.ellipse((cx - 21, 303 - 21, cx + 21, 303 + 21), fill=0)

    # 24dp status-bar icons; the mark fills ~92% of the width (it is wider than tall), centred
    for dpi, px in {"mdpi": 24, "hdpi": 36, "xhdpi": 48, "xxhdpi": 72, "xxxhdpi": 96}.items():
        tw = round(px * 0.92)
        th = round(tw * im.size[1] / im.size[0])
        alpha = Image.new("L", (px, px), 0)
        alpha.paste(im.resize((tw, th), Image.LANCZOS), ((px - tw) // 2, (px - th) // 2))
        out = Image.new("RGBA", (px, px), (255, 255, 255, 0))
        out.putalpha(alpha)
        save(out, os.path.join(RES, f"drawable-{dpi}", "ic_notification_icon.png"))


def save(img, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path, "PNG")


if "--notif-only" in __import__("sys").argv:                         # just the notification icon; leave the launcher icons alone
    notification_icons()
    print("notification icons generated OK")
    raise SystemExit(0)

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

notification_icons()

print("icons generated OK")

"""Generate the 1024x500 Play Store feature graphic from icon-master.png.
Run: backend/.venv/Scripts/python.exe android-twa/gen_feature_graphic.py

Play requires exactly 1024x500, PNG/JPEG, no transparency. Palette and type
roles follow BRAND-UI-PLAN.md (navy canvas, gold as the single accent).
Cormorant Garamond / Inter aren't installed on Windows, so the nearest system
stand-ins are used: Constantia for the display serif, Segoe UI for body.
"""
import os
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.abspath(__file__))
MASTER = os.path.join(ROOT, "icon-master.png")
OUT = os.path.join(ROOT, "play-feature-1024x500.png")

W, H = 1024, 500

BG_0 = (7, 10, 20)
BG_1 = (11, 16, 32)
INK = (243, 236, 216)
INK_DIM = (200, 189, 158)
GOLD_LT = (247, 224, 138)
GOLD = (212, 175, 55)
GOLD_DK = (154, 111, 20)

FONTS = "C:/Windows/Fonts"
F_SERIF = os.path.join(FONTS, "constanb.ttf")   # display — stands in for Cormorant Garamond
F_SANS = os.path.join(FONTS, "segoeui.ttf")     # body — stands in for Inter
F_SANS_LT = os.path.join(FONTS, "segoeuisl.ttf")


def font(path, size):
    return ImageFont.truetype(path, size)


def vertical_gradient(size, top, bottom):
    w, h = size
    grad = Image.new("RGB", (1, h))
    px = grad.load()
    for y in range(h):
        t = y / max(h - 1, 1)
        px[0, y] = tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
    return grad.resize((w, h), Image.BICUBIC)


def diagonal_gold(size):
    """The --gold-grad ramp (135deg: gold-lt -> gold 48% -> gold-dk)."""
    w, h = size
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            t = (x / max(w - 1, 1) + y / max(h - 1, 1)) / 2
            if t < 0.48:
                u = t / 0.48
                c = tuple(round(GOLD_LT[i] + (GOLD[i] - GOLD_LT[i]) * u) for i in range(3))
            else:
                u = (t - 0.48) / 0.52
                c = tuple(round(GOLD[i] + (GOLD_DK[i] - GOLD[i]) * u) for i in range(3))
            px[x, y] = c
    return img


def aurora(base):
    """Slow radial blobs behind everything — brand's 'aurora background', very low opacity."""
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.ellipse((-140, -190, 430, 330), fill=(212, 175, 55, 26))     # gold, upper left
    d.ellipse((560, 210, 1180, 690), fill=(79, 214, 160, 16))      # faint teal, lower right
    d.ellipse((300, -230, 820, 210), fill=(90, 110, 220, 14))      # cool wash, top
    layer = layer.filter(ImageFilter.GaussianBlur(120))
    base.paste(layer, (0, 0), layer)
    return base


def gradient_text(canvas, xy, text, fnt, ramp):
    """Draw text filled with a gradient, by using the glyphs as a mask."""
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).text(xy, text, font=fnt, fill=255)
    canvas.paste(ramp, (0, 0), mask)


def main():
    img = vertical_gradient((W, H), BG_1, BG_0)
    img = aurora(img)

    # The D-mark, left side, with a soft gold rim-light behind it.
    mark = Image.open(MASTER).convert("RGBA").resize((248, 248), Image.LANCZOS)
    mx, my = 96, (H - 248) // 2
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((mx - 34, my - 34, mx + 282, my + 282), fill=(212, 175, 55, 34))
    glow = glow.filter(ImageFilter.GaussianBlur(52))
    img.paste(glow, (0, 0), glow)
    img.paste(mark, (mx, my), mark)

    ramp = diagonal_gold((W, H))
    tx = 396

    # The mark already carries the "DUSU" wordmark, so the copy leads with the
    # promise instead of repeating the name.
    f_hero = font(F_SERIF, 74)
    gradient_text(img, (tx, 112), "Speak with", f_hero, ramp)
    gradient_text(img, (tx, 196), "Confidence", f_hero, ramp)

    d = ImageDraw.Draw(img)
    d.line((tx + 4, 306, tx + 132, 306), fill=GOLD, width=2)

    d.text((tx, 330), "Practice spoken English out loud with an AI",
           font=font(F_SANS, 26), fill=INK)
    d.text((tx, 364), "coach that remembers you.",
           font=font(F_SANS, 26), fill=INK)
    d.text((tx, 414), "TALK  ·  INTERVIEW PREP  ·  DAILY HINDI  ·  LEARN",
           font=font(F_SANS_LT, 18), fill=INK_DIM)

    # Flatten to RGB — Play rejects transparency in the feature graphic.
    img.convert("RGB").save(OUT, "PNG")
    print(f"wrote {OUT} {Image.open(OUT).size} {Image.open(OUT).mode}")


if __name__ == "__main__":
    main()

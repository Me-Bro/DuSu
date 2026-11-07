"""Does the printed QR actually scan?  Run through verify.sh (python:3.12-slim + opencv + zxing-cpp).

Inputs (made by verify.sh, all at 300 dpi from the PDFs): .work/dark300.png, .work/print-colour300.png, .work/print-bw300.png,
plus out/DuSu-poster-share.png.  Two independent decoders: zxing-cpp (the engine family phones use) and OpenCV.
Every REQUIRED case must decode to EXACTLY the URL in qr-meta.json with zxing-cpp; the print cases also simulate what office
printers and photocopiers do to a page (1-bit dithering, toner running low, ink spreading, thin print).
"""
import io
import json
import re
import sys

import cv2
import numpy as np
import zxingcpp
from PIL import Image, ImageFilter

META = json.load(open("qr-meta.json", encoding="utf-8"))
URL = META["url"]
HTML = open("poster.html", encoding="utf-8").read()
fails = []
RESULTS = {"pass": 0, "optional_miss": 0}


def zx(img):
    r = zxingcpp.read_barcodes(img, formats=zxingcpp.BarcodeFormat.QRCode, try_rotate=True, try_downscale=True, try_invert=False)
    return [x.text for x in r]


def cv(img):
    a = np.array(img.convert("RGB"))[:, :, ::-1]
    out = []
    try:
        t, _, _ = cv2.QRCodeDetectorAruco().detectAndDecode(a)
        if t:
            out.append(t)
    except Exception:
        pass
    if not out:
        t, _, _ = cv2.QRCodeDetector().detectAndDecode(a)
        if t:
            out.append(t)
    return out


def case(group, name, img, must_cv=False, required=True):
    z, c = zx(img), cv(img)
    okz, okc = URL in z, URL in c
    tag = "PASS" if okz else ("FAIL" if required else "miss")
    print(f"{tag} zxing  {'PASS' if okc else 'fail'} opencv   [{group}] {name}   ({img.size[0]}x{img.size[1]})")
    if okz:
        RESULTS["pass"] += 1
    elif required:
        fails.append(f"zxing: [{group}] {name}")
    else:
        RESULTS["optional_miss"] += 1
    if must_cv and not okc:
        fails.append(f"opencv: [{group}] {name}")


def geometry(group, css_width_mm):
    total = META["total_modules_with_border"]
    code_mm = css_width_mm * META["modules"] / total
    print(f"[{group}] QR svg {css_width_mm} mm, code {code_mm:.1f} mm, module {css_width_mm / total:.2f} mm, "
          f"quiet zone {css_width_mm * META['border'] / total:.1f} mm ({META['border']} modules), version {META['version']}, ECC {META['error']}")
    if code_mm < 50.0:
        fails.append(f"[{group}] code is only {code_mm:.1f} mm wide (< 50)")
    if META["border"] < 4:
        fails.append("quiet zone < 4 modules")


# ---------- image degradations ----------
def shrink(im, f):
    return im.resize((max(1, int(im.width * f)), max(1, int(im.height * f))), Image.LANCZOS)


def jpeg(im, q):
    b = io.BytesIO()
    im.save(b, "JPEG", quality=q)
    b.seek(0)
    return Image.open(b).convert("RGB")


def on_grey(im, rot=0, margin=0.12, grey=(118, 118, 112)):
    r = im.rotate(rot, expand=True, resample=Image.BICUBIC, fillcolor=grey) if rot else im
    canvas = Image.new("RGB", (int(r.width * (1 + 2 * margin)), int(r.height * (1 + 2 * margin))), grey)
    canvas.paste(r, (int(r.width * margin), int(r.height * margin)))
    return canvas


def tilt(im, k=0.10):
    a = np.array(im)
    h, w = a.shape[:2]
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst = np.float32([[w * k, h * k * 0.6], [w * (1 - k * 0.3), 0], [w, h], [0, h * (1 - k * 0.5)]])
    return Image.fromarray(cv2.warpPerspective(a, cv2.getPerspectiveTransform(src, dst), (w, h), borderValue=(110, 110, 105)))


def lowlight(im):
    a = (np.array(im).astype(np.float32) / 255.0) ** 1.6 * 0.55
    a = a + np.random.default_rng(7).normal(0, 0.02, a.shape)
    return Image.fromarray((np.clip(a, 0, 1) * 255).astype(np.uint8))


def one_bit(im, dpi_from=300, dpi_to=150):
    """What a black-and-white laser printer / photocopier lays down: grayscale -> error-diffusion halftone at its resolution."""
    g = im.convert("L")
    g = g.resize((int(g.width * dpi_to / dpi_from), int(g.height * dpi_to / dpi_from)), Image.LANCZOS)
    return g.convert("1").convert("RGB")           # Floyd-Steinberg dither


def toner_low(im, k=0.55):
    a = np.array(im.convert("RGB")).astype(np.float32)
    return Image.fromarray((255 - (255 - a) * (1 - k)).astype(np.uint8))   # every dark tone pulled toward white


def dot_gain(im, px=3):
    g = np.array(im.convert("L"))
    return Image.fromarray(cv2.erode(g, np.ones((px, px), np.uint8))).convert("RGB")   # dark ink spreads (erode = grow dark)


def thin_print(im, px=3):
    g = np.array(im.convert("L"))
    return Image.fromarray(cv2.dilate(g, np.ones((px, px), np.uint8))).convert("RGB")  # dark ink shrinks (dilate = grow white)


def photocopy_of_photocopy(im):
    first = one_bit(im, 300, 150)
    soft = first.filter(ImageFilter.GaussianBlur(1.1))
    return one_bit(soft.resize((int(soft.width * 2), int(soft.height * 2)), Image.LANCZOS), 300, 130)


def suite(group, page, printer):
    case(group, "whole page, 300 dpi", page, must_cv=True)
    cases = [
        ("25% size", shrink(page, 0.25), True, True),
        ("20% size", shrink(page, 0.20), False, True),
        ("gaussian blur r=2.5 @50%", shrink(page, 0.5).filter(ImageFilter.GaussianBlur(2.5)), False, True),
        ("JPEG q40 @50%", jpeg(shrink(page, 0.5), 40), True, True),
        ("JPEG q30 @30%", jpeg(shrink(page, 0.3), 30), False, True),
        ("rotated 15 deg on grey @50%", on_grey(shrink(page, 0.5), rot=15), True, True),
        ("rotated -30 deg on grey @40%", on_grey(shrink(page, 0.4), rot=-30), False, True),
        ("tilted (perspective) @50%", tilt(shrink(page, 0.5)), True, True),
        ("on grey background (photo with margin) @35%", on_grey(shrink(page, 0.35)), True, True),
        ("low light + noise @50%", lowlight(shrink(page, 0.5)), False, True),
        ("grayscale @40%", shrink(page, 0.4).convert("L").convert("RGB"), True, True),
        ("blur + JPEG q50 + rotate 10 + grey @40% (combined)", on_grey(jpeg(shrink(page, 0.4).filter(ImageFilter.GaussianBlur(1.5)), 50), rot=10), False, True),
    ]
    if printer:
        cases += [
            # the page as an office / copy-shop machine would actually put it on paper, then photographed or scanned
            ("1-bit halftone @150 dpi (laser / photocopier)", one_bit(page, 300, 150), True, True),
            ("1-bit halftone @100 dpi (draft mode)", one_bit(page, 300, 100), False, True),
            ("1-bit halftone @150 dpi, then photographed small @40%", shrink(one_bit(page, 300, 150), 0.4 * 2), False, True),
            ("photocopy of a photocopy (halftone, blur, halftone)", photocopy_of_photocopy(page), False, False),
            ("toner / ink running low (-55%)", toner_low(page, 0.55), True, True),
            ("toner / ink running very low (-70%)", toner_low(page, 0.70), False, False),
            ("dot gain (ink spreads ~0.25 mm)", dot_gain(page, 3), True, True),
            ("dot gain (ink spreads ~0.4 mm)", dot_gain(page, 5), False, False),
            ("thin print (ink shrinks ~0.25 mm)", thin_print(page, 3), True, True),
            ("thin print (ink shrinks ~0.4 mm)", thin_print(page, 5), False, False),
            ("halftone + low toner + rotated 8 deg on grey @50%", on_grey(shrink(toner_low(one_bit(page, 300, 150).resize(page.size), 0.4), 0.5), rot=8), False, False),
        ]
    for name, im, must, req in cases:
        case(group, name, im, must_cv=False, required=req)


w_dark = float(re.search(r"\.qrcard svg\{[^}]*width:([\d.]+)mm", HTML).group(1))
w_print = float(re.search(r"html\.print \.qrcard svg\{[^}]*width:([\d.]+)mm", HTML).group(1))

import os
if os.path.exists(".work/dark300.png") and os.path.exists("out/DuSu-poster-share.png"):   # only when VARIANT=dark was built
    geometry("dark", w_dark)
    suite("dark", Image.open(".work/dark300.png").convert("RGB"), printer=False)
    case("dark", "share PNG 1080 px, whole page", Image.open("out/DuSu-poster-share.png").convert("RGB"), must_cv=True)
    share = Image.open("out/DuSu-poster-share.png").convert("RGB")
    for px in (720, 540):
        case("dark", f"share PNG shown at {px} px wide", share.resize((px, int(share.height * px / share.width)), Image.LANCZOS), required=True)
else:
    print("(dark version not built - skipped; the two printer versions are checked below)")

for g in ("print-colour", "print-bw"):
    geometry(g, w_print)
    suite(g, Image.open(f".work/{g}300.png").convert("RGB"), printer=True)

print()
print(f"{RESULTS['pass']} cases decoded; {RESULTS['optional_miss']} extreme (optional) cases did not")
if fails:
    print("FAILED:", "; ".join(fails))
    sys.exit(1)
print("all required QR checks passed")

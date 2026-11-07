"""Copy / legibility audit of poster.html against the marketing plan's truth rules.  Exit 1 on any failure."""
import re
import sys
from html.parser import HTMLParser

SRC = open("poster.html", encoding="utf-8").read()
fails = []


class T(HTMLParser):
    SKIP = {"style", "script", "svg", "title", "head"}

    def __init__(self):
        super().__init__()
        self.stack, self.blocks, self.cur = [], [], []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.stack.append(tag)
        elif not self.stack:
            self.cur.append(" ")   # a tag boundary is a word boundary (adjacent spans must not glue together)

    def handle_endtag(self, tag):
        if self.stack and self.stack[-1] == tag:
            self.stack.pop()
        elif not self.stack:
            self.cur.append(" ")
        if tag in ("p", "h1", "h2", "h3", "h4", "div", "section", "header", "footer"):
            if self.cur:
                self.blocks.append(" ".join("".join(self.cur).split()))
                self.cur = []

    def handle_data(self, data):
        if not self.stack and data.strip():
            self.cur.append(data)


t = T()
t.feed(SRC)
if t.cur:
    t.blocks.append(" ".join("".join(t.cur).split()))
blocks = [b for b in t.blocks if b]
text = "\n".join(blocks)
print(f"{len(blocks)} text blocks, {len(text)} characters of visible text")

# 1. words / symbols the marketing plan forbids
banned = {
    "download": r"download|डाउनलोड|डाऊनलोड|play\s*store|प्ले\s*स्टोर",
    "unlimited / always free": r"unlimited|अनलिमिटेड|असीमित|हमेशा|सदा\s*फ्री|हमेशा\s*फ्री|lifetime|लाइफटाइम",
    "price / money": r"₹|rs\.?\s*\d|\$|रुपय|कीमत|पैसे|मुफ्त\s*में\s*सब",
    "superlative / proof we don't have": r"नंबर\s*1|no\.?\s*1|सर्वश्रेष्ठ|बेस्ट|best|लाख|हज़ार|हजार|users|यूज़र्स|रेटिंग|rating|review|रिव्यू|testimonial|⭐|★",
    "guarantee of an outcome": r"100\s*%|पक्का|जरूर\s*मिलेगी|नौकरी\s*मिलेगी|selection|सेलेक्शन\s*पक्का",
    "company claim for Rana Brothers": r"कंपनी|कम्पनी|company|pvt|ltd|प्राइवेट",
    "voice-privacy claim": r"आवाज़\s*सेव|रिकॉर्डिंग\s*(नहीं|सेव)|we don.t store|सुरक्षित",
    "emoji / pictographs": "[\U0001F300-\U0001FAFF☀-➿]",
}
for name, rx in banned.items():
    m = re.search(rx, text, re.I)
    print(f"{'FAIL' if m else 'ok  '}  no {name}" + (f"  -> {m.group(0)!r}" if m else ""))
    if m:
        fails.append(name)

# 2. 'free' only ever together with the 2-own-keys caveat (same block)
for b in blocks:
    if re.search(r"फ्री|free|मुफ़्त|मुफ्त", b, re.I) and not re.search(r"\bkey\b|की\b.*key", b):
        # the Q&A heading "क्या यह फ्री है?" is a question; its answer block carries the caveat (checked below)
        if b.strip() in ("क्या यह फ्री है?",):
            continue
        print("FAIL  'free' without the keys caveat:", b)
        fails.append("free without keys caveat: " + b[:40])
ans = [b for b in blocks if b.startswith("फ्री में शुरू")]
print(("ok  " if ans and "2 फ्री AI key" in ans[0] else "FAIL") + "  the 'is it free?' answer states the 2-keys condition")
if not (ans and "2 फ्री AI key" in ans[0]):
    fails.append("free answer lacks the caveat")

# 3. the job disclaimer is there, and 'guarantee' only appears negated
gar = [b for b in blocks if "गारंटी" in b]
okg = len(gar) == 1 and "नहीं" in gar[0]
print(("ok  " if okg else "FAIL") + "  'गारंटी' appears once, negated (no job guarantee)")
if not okg:
    fails.append("guarantee wording")

# 4. only these Latin tokens are allowed (brand + the product's own words); no digits other than the step numbers and '2 keys'
latin = set(re.findall(r"[A-Za-z][A-Za-z.\-]*", text))
allowed = {"DuSu", "AI", "Chrome", "Google", "Android", "key", "QR", "dusu.ranabrothers.online"}
extra = latin - allowed
print(("ok  " if not extra else "FAIL") + f"  Latin words limited to the brand/product words {sorted(allowed)}" + (f"  extra: {sorted(extra)}" if extra else ""))
if extra:
    fails.append("unexpected Latin words " + str(sorted(extra)))
digits = set(re.findall(r"\d", text))
okd = digits <= {"1", "2", "3"}
print(("ok  " if okd else "FAIL") + f"  digits used: {sorted(digits)} (only the step numbers and '2 keys')")
if not okd:
    fails.append("digits")

# 5. never 'DuSu' in Devanagari, never the product name misspelt
bad_name = re.findall(r"डूसू|दुसू|डुसु|Dusu\b|DUSU\b|dusu\b(?!\.)", text)
print(("ok  " if not bad_name else "FAIL") + "  the product name is always written 'DuSu'" + (f" -> {bad_name}" if bad_name else ""))
if bad_name:
    fails.append("product name spelling")

# 6. the link text on the poster matches the QR's host
host = re.search(r"https?://([^/]+)/", open("qr-meta.json").read().replace("\\/", "/") + "/")
import json
qr_host = re.match(r"https?://([^/]+)", json.load(open("qr-meta.json"))["url"]).group(1)
print(("ok  " if qr_host in text else "FAIL") + f"  the printed address '{qr_host}' is the QR's host")
if qr_host not in text:
    fails.append("printed host differs from QR host")

# 7. font sizes (pt) and contrast
sizes = [(float(m.group(1)), m.group(0)) for m in re.finditer(r"font:\s*(?:\d{3}\s+)?([\d.]+)pt", SRC)]
smallest = min(s for s, _ in sizes)
body_like = sorted({s for s, _ in sizes if s < 11})
print(f"smallest text {smallest} pt (fine print); other sizes below 11 pt: {body_like}")
if smallest < 8.0:
    fails.append("text below 8 pt")
if min(s for s in {s for s, _ in sizes} if s != smallest) < 10.0:
    fails.append("secondary text below 10 pt")


def lum(hexc):
    h = hexc.lstrip("#")
    r, g, b = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def ratio(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


# worst plausible backgrounds: the lightest navy, and navy under the strongest glow (violet at 30 %)
bgs = {"navy #101a4a": "#101a4a", "under violet glow": "#3a3a78", "card glass": "#1d2552"}
fgs = {"white": "#ffffff", "ink2 (body)": "#c9d2f2", "fine print": "#aeb8dc", "amber": "#ffb23f", "cyan": "#35c7ff", "ivory": "#e6ebfb"}
worst = 99
for bn, bc in bgs.items():
    for fn, fc in fgs.items():
        worst = min(worst, ratio(fc, bc))
print(f"lowest text/background contrast over the worst backgrounds: {worst:.1f}:1 (need >= 4.5)")
if worst < 4.5:
    fails.append("contrast")

# 8. printer themes: text colours on WHITE paper, and no ink fills in the print CSS
print_css = SRC[SRC.index("PRINTER-FRIENDLY THEMES"):SRC.index("</style>", SRC.index("PRINTER-FRIENDLY THEMES"))]
white = "#ffffff"
for var, need in (("ink", 4.5), ("ink2", 4.5), ("acc", 4.5), ("blue", 4.5), ("line", 3.0)):
    for hexc in re.findall(rf"--p-{var}:(#[0-9a-fA-F]{{6}})", print_css):
        r = ratio(hexc, white)
        print(f"{'ok  ' if r >= need else 'FAIL'}  print colour --p-{var} {hexc} on white {r:.1f}:1 (need >= {need})")
        if r < need:
            fails.append(f"print colour {var} {hexc} {r:.1f}:1")
for stop in re.findall(r"--p-grad:linear-gradient\(([^)]*)\)", print_css):
    for hexc in re.findall(r"#[0-9a-fA-F]{6}", stop):
        r = ratio(hexc, white)
        print(f"{'ok  ' if r >= 3.0 else 'FAIL'}  headline gradient stop {hexc} on white {r:.1f}:1 (large text, need >= 3)")
        if r < 3.0:
            fails.append(f"gradient stop {hexc}")
for hexc in re.findall(r"--d:(#[0-9a-fA-F]{6})", SRC):
    r = ratio(hexc, white)
    if r < 3.0:
        print(f"FAIL  icon colour {hexc} on white {r:.1f}:1 (need >= 3)")
        fails.append(f"icon colour {hexc}")
print("ok    every card icon colour is >= 3:1 on white")
# no solid fills in the print CSS: the only 'background' values allowed are none / #fff / the text gradient (clipped to the glyphs)
bad_bg = []
for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", print_css):
    sel, body = m.group(1).strip(), m.group(2)
    for bg in re.findall(r"background(?:-color)?\s*:\s*([^;]+)", body):
        bg = bg.strip()
        if bg in ("none", "#fff", "#ffffff", "transparent") or ("var(--p-grad)" in bg and "background-clip" in body):
            continue
        hm = re.search(r"(?<![\w-])height\s*:\s*([\d.]+)mm", body)
        if sel.endswith("::before") and hm and float(hm.group(1)) <= 1.0:   # a hairline accent rule, not a block of ink
            continue
        bad_bg.append(f"{sel}: {bg}")
print(("ok  " if not bad_bg else "FAIL") + "  the printer themes use no filled backgrounds (only paper white and text-clipped gradient)" + (f" -> {bad_bg}" if bad_bg else ""))
if bad_bg:
    fails.append("filled background in the print CSS")

print("chip text on cyan:", f"{ratio('#0a1030', '#35c7ff'):.1f}:1", "| step numbers on amber:", f"{ratio('#0a1030', '#ffb23f'):.1f}:1")

print()
if fails:
    print("AUDIT FAILED:", "; ".join(fails))
    sys.exit(1)
print("copy audit passed")

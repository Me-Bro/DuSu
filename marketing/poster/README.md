# DuSu A4 poster (Hindi) — intro, QR code, 3 short Q&As

Made 2026-10-29. Everything except "DuSu", "AI", "Chrome", "Google", "Android", "key", "QR" and the web address is Hindi (Devanagari). Three versions of the same poster, so pick by how you will print:

| File | Use it for | Ink |
|---|---|---|
| `out/DuSu-poster-A4-print-colour.pdf` | **Your office / home / copy-shop COLOUR printer.** White paper, colour only in text and thin lines, nothing in the outer 12 mm (printers cannot print the edges). Exactly A4. | ~**13x less ink** than the dark poster |
| `out/DuSu-poster-A4-print-bw.pdf` | **Black-and-white laser printer or photocopy shop** (the cheapest way to make 50 copies). Black only, no grey fills; the QR is pure black. | ~**17x less ink** than the dark poster |
| `out/DuSu-poster-A4-print-colour.png` / `-print-bw.png` | Pictures of the same pages (200 dpi) - the colour one also works for sharing on WhatsApp / Instagram. | n/a |

Copies with plain names are in `~/Desktop/DuSu-Poster/` (`1-...COLOUR-printer.pdf`, `2-...BLACK-WHITE-printer.pdf`, `3-...for-WhatsApp.png`). The `out/` folder is rebuilt by `build.sh`; the Desktop copies are not.

The original **dark** version (navy full-page, 3 mm bleed, for a professional print shop or screens) is no longer built by default because it uses far too much ink for an office printer: `VARIANT=dark ./build.sh` (or `VARIANT=all`) makes `out/DuSu-poster-A4.pdf`, its PNG and `out/DuSu-poster-share.png`.

Measured with the same method on all three versions (`ink_report.py`): the dark poster covers 94.7 % of the page and uses about 43 % ink; the colour printer version covers 11.7 % and uses 3.2 %; the black-only version covers 11.8 % and uses 2.5 % (about what an ordinary page of text uses). The numbers compare versions, they do not price a print.

**How to print (office / home):** open the PDF, paper **A4**, scale **100 % / "Actual size"** (not "Fit to page"), and "Economy / Draft" mode is fine. Never print the dark one on an office printer: it soaks the page and leaves white edges.

The QR opens `https://dusu.ranabrothers.online/?s=poster`. The `?s=poster` tag lets you count visits from the poster with the plan's read-only command (visits, not sign-ups):
`docker logs dusu-backend-1 --since 168h | grep -c "GET /?s=poster"`

## Change something and rebuild

* Words, colours, layout: edit `poster.html` (plain HTML + CSS, sizes in mm / pt). The two printer versions are the `html.print` / `html.print.mono` block at the end of its `<style>`; the Hindi text exists once and is shared by all three.
* The link: edit `URL` in `make_qr.py` (and the printed address in `poster.html`).
* Rebuild: `marketing/poster/build.sh` (the two printer versions; needs Docker, and the Playwright modules the test suites already use at `~/.cache/dusu-ri-pwrun/node_modules`; set `PW_MODULES` to use another folder). `VARIANT=print-bw build.sh` builds one version; `build.sh guides` writes `out/debug-guides-*.png` with the safe-area line instead of the final files.
* Check it: `marketing/poster/verify.sh`:
  * every PDF is one page of the right size with embedded fonts;
  * **printer checks** on the finished pages: nothing printed in the outer 11.5 mm, ink budget (area <= 20 %, density <= 8 %), the black-only PDF has no colour pixel at all;
  * **QR** decoded by two independent decoders (zxing-cpp, OpenCV) from the PDFs, the share image and 60+ bad copies: small, blurred, JPEG, rotated, tilted, low light, grayscale, and — for the printer versions — what printers do: 1-bit halftone at 150 / 100 dpi (laser, photocopier, draft), a photocopy of a photocopy, toner / ink running low (-55 %, -70 %), ink spreading and thinning by 0.25 / 0.4 mm;
  * the copy audit (`audit_copy.py`): marketing-plan rules, type sizes, contrast on dark **and on white**, no filled backgrounds in the printer CSS.
  `render.js` also refuses to finish if a font fails to load, the headline wraps, or anything leaves the safe margin.

## How it is built

`poster.html` is one file (CSS + inline icons). `make_qr.py` writes `qr.svg` (version 4, 33 x 33 modules, error correction Q, 4-module quiet zone, no logo in the middle; printed 50.4 mm wide on the dark poster, 53.1 mm on the printer versions). `render.js` (Playwright / Chromium in Docker) writes the PDFs and PNGs. Fonts are in `fonts/` (Baloo 2 for headlines, Mukta for text; both SIL Open Font License, licence files included) because the rendering container has no Devanagari font. `logo.png` is a copy of `backend/logo.png`. `CLAIMS.md` lists every claim on the poster and its source.

**Two things the checks caught while building the printer versions:** the QR was navy (a colour printer would mix coloured ink for it, a B&W one would have to guess) - it is pure black now; and the Devanagari letter "त" in the "तीन आसान कदम" heading pokes 0.7 mm outside its text box, into the margin printers cannot print - only a check on the finished page could see that (the layout check looks at boxes), so the heading has a small indent.

## What is NOT verified (please do)

* **A real phone scanning a real print**, at 1 m and 2 m, with two different phones - print the colour AND the black-and-white version on your actual printer (and one photocopy of it). The simulations are strong evidence, not proof.
* **Your printer's real margins and colours.** The page keeps 12 mm clear, which every printer handles, but check the QR frame and the coloured headline look right on your machine.
* **The Hindi** has not been read by a native speaker. It is my draft in the app's own style.
* **Which features are live in production.** `CLAIMS.md` lists each claim and its source; the repo docs say all six are on for everyone, but nobody checked the production switches (Practice Room in particular).
* The marketing plan asks that links go public only after the "G0" 10-friend smoke test. The poster is honest about the two-free-keys step, but when to print is your call.

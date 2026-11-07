#!/usr/bin/env bash
# Build the DuSu A4 poster (two printer-friendly versions by default; the dark print-shop/screen version on request):
#   QR -> static fonts -> HTML -> PDF + PNGs.     marketing/poster/build.sh [guides]      VARIANT=dark|print-colour|print-bw
# Needs Docker (python:3.12-slim, mcr.microsoft.com/playwright:v1.60.0-noble) and the Playwright node modules
# at $PW_MODULES (default ~/.cache/dusu-ri-pwrun/node_modules - the same ones the test suites use).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PW="${PW_MODULES:-$HOME/.cache/dusu-ri-pwrun/node_modules}"
cd "$HERE"

# 1. QR code + static (non-variable) Baloo 2 instances, so the PDF embeds plain fonts
docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -e PYTHONUSERBASE=/tmp/.local -v "$HERE":/w -w /w python:3.12-slim sh -c '
  pip install -q --disable-pip-version-check --user segno==1.6.6 fonttools==4.55.3 >/dev/null 2>&1
  export PATH=/tmp/.local/bin:$PATH
  python make_qr.py
  [ -f fonts/Baloo2-ExtraBold.ttf ] || fonttools varLib.instancer fonts/Baloo2-Variable.ttf wght=800 -o fonts/Baloo2-ExtraBold.ttf -q
  [ -f fonts/Baloo2-Bold.ttf ]      || fonttools varLib.instancer fonts/Baloo2-Variable.ttf wght=700 -o fonts/Baloo2-Bold.ttf -q
'

# 2. inline the QR into the page
python3 - <<'PY'
import pathlib
h = pathlib.Path("poster.html").read_text(encoding="utf-8")
q = pathlib.Path("qr.svg").read_text(encoding="utf-8")
assert "<!--QR-->" in h
pathlib.Path("poster.built.html").write_text(h.replace("<!--QR-->", q), encoding="utf-8")
PY

# 3. render the two printer versions by default (VARIANT=dark -> the dark print-shop/screen version, VARIANT=all -> all three, VARIANT=print-bw -> one;
#    GUIDES=1 via "build.sh guides" -> only debug pictures with the safe-area line)
G=0; [ "${1:-}" = guides ] && G=1
docker run --rm --ipc=host --user "$(id -u):$(id -g)" -e HOME=/tmp -e NODE_PATH=/pw/node_modules -e GUIDES=$G -e VARIANT="${VARIANT:-print}" \
  -v "$PW":/pw/node_modules:ro -v "$HERE":/w -w /w mcr.microsoft.com/playwright:v1.60.0-noble node render.js

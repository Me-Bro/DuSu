#!/usr/bin/env bash
# Verify the built posters (dark + two printer versions): PDF facts, printer-friendliness, QR decoding, copy audit.
#   marketing/poster/verify.sh        (run build.sh first)
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"
mkdir -p .work

echo "== PDFs =="
# name | width pt | height pt   (216x303 mm and A4 210x297 mm; +-0.6 pt)
for spec in "DuSu-poster-A4.pdf 612.28 858.90 dark" "DuSu-poster-A4-print-colour.pdf 595.28 841.89 print-colour" "DuSu-poster-A4-print-bw.pdf 595.28 841.89 print-bw"; do
  set -- $spec
  f="out/$1"
  if [ ! -f "$f" ]; then echo "skip: $1 (not built; VARIANT=dark ./build.sh to make it)"; continue; fi
  pdfinfo "$f" | awk -v W="$2" -v H="$3" -v N="$1" '/^Pages:/{p=$2} /^Page size:/{w=$3;h=$5} END{
    d1=w-W; d2=h-H; if(d1<0)d1=-d1; if(d2<0)d2=-d2;
    if(p!=1||d1>0.7||d2>0.7){print "FAIL " N ": expected 1 page of " W " x " H " pt, got " p " page(s) of " w " x " h; exit 1}
    else print "ok: " N " - 1 page, " w " x " h " pt" }'
  if pdffonts "$f" | awk 'NR>2{print $2,$3}' | grep -q "Type 3"; then echo "FAIL: a Type 3 font is in $f"; exit 1; fi
  pdffonts "$f" | awk -v N="$1" 'NR>2 && $(NF-4)!="yes" {print "FAIL not embedded in " N ": " $0; bad=1} END{exit bad}'
  pdftoppm -r 300 -png -singlefile "$f" ".work/${4}300"
done
echo "fonts: all embedded, no Type 3"

echo "== printer checks (margins, ink, colour) and QR decoding =="
docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -e PYTHONUSERBASE=/tmp/.local -v "$HERE":/w -w /w python:3.12-slim sh -c '
  pip install -q --disable-pip-version-check --user opencv-python-headless numpy pillow zxing-cpp >/dev/null 2>&1
  python verify_print.py && python verify_qr.py'

echo "== copy audit =="
python3 audit_copy.py

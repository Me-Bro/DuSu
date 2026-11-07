#!/usr/bin/env bash
# Run one audit spec in a real Chromium against the RUNNING audit app (tests/audit/up.sh). The browser shares the server's network namespace, so the page is
# http://localhost:8000 - a secure context, as production's https is - and nothing can leave the box. Extra env vars are passed through:  AUD_ENV="A=1 B=2" tests/audit/spec.sh walk.cjs
#   tests/audit/spec.sh walk.cjs
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
[ -f "$HERE/.out/env" ] || { echo "the audit app is not up (tests/audit/up.sh)"; exit 2; }
mapfile -t L < "$HERE/.out/env"
SRV="${L[2]}"
PW="${PW_MODULES:-$HOME/.cache/dusu-ri-pwrun/node_modules}"
OUT="${OUT_DIR:-$HOME/.cache/dusu-audit-shots}"
mkdir -p "$OUT"
EXTRA=(); for kv in ${AUD_ENV:-}; do EXTRA+=(-e "$kv"); done
docker run --rm --ipc=host --network "container:$SRV" --user "$(id -u):$(id -g)" -e HOME=/tmp -e NODE_PATH=/pw/node_modules -e OUT=/out -e BASE="http://localhost:8000" \
  -e TOKENS=/repo/tests/audit/.out/tokens.json -e FONTS=/repo/tests/audit/.fonts "${EXTRA[@]}" \
  -v "$REPO":/repo:ro -v "$PW":/pw/node_modules:ro -v "$OUT":/out -v "$HERE/.fonts/deva":/usr/share/fonts/truetype/dusu-deva:ro -w /repo/tests/audit \
  mcr.microsoft.com/playwright:v1.60.0-noble node "$@"

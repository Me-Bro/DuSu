#!/usr/bin/env bash
# Cold-open performance of the LIVE public page (read-only: it loads the home page like any visitor). Needs the internet, so it does NOT use the scratch network.
#   tests/audit/live.sh
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
PW="${PW_MODULES:-$HOME/.cache/dusu-ri-pwrun/node_modules}"
OUT="${OUT_DIR:-$HOME/.cache/dusu-audit-shots}"
mkdir -p "$OUT"
docker run --rm --ipc=host --user "$(id -u):$(id -g)" -e HOME=/tmp -e NODE_PATH=/pw/node_modules -e OUT=/out -e LIVE_URL="${LIVE_URL:-https://dusu.ranabrothers.online/}" \
  -v "$REPO":/repo:ro -v "$PW":/pw/node_modules:ro -v "$OUT":/out -w /repo/tests/audit mcr.microsoft.com/playwright:v1.60.0-noble node live.cjs

#!/usr/bin/env bash
# Run one browser spec that needs no server (static.spec.cjs, shots.cjs ...) inside the Playwright image.
#   tests/lab/browser/run.sh static.spec.cjs
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
PW="${PW_MODULES:-$HOME/.cache/dusu-ri-pwrun/node_modules}"
OUT="${OUT_DIR:-$HOME/.cache/dusu-lab-shots}"
mkdir -p "$OUT"
SPEC="$1"; shift || true
exec docker run --rm --ipc=host --user "$(id -u):$(id -g)" -e HOME=/tmp -e NODE_PATH=/pw/node_modules -e OUT=/out -e REPO=/repo -e VERBOSE -e HTML_SRC \
  ${ORIG_HTML_HOST:+-v "$ORIG_HTML_HOST":/orig.html:ro -e ORIG_HTML=/orig.html} \
  -v "$REPO":/repo:ro -v "$PW":/pw/node_modules:ro -v "$OUT":/out -w /repo/tests/lab/browser \
  mcr.microsoft.com/playwright:v1.60.0-noble node "$SPEC" "$@"

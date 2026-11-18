#!/usr/bin/env bash
# Run one browser spec that needs no server (static.spec.cjs, oldnew.spec.cjs, shots) inside the Playwright image.
#   tests/talk/browser/run.sh static.spec.cjs        ORIG_HTML_HOST=/abs/path/in/the/repo.html tests/talk/browser/run.sh oldnew.spec.cjs
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
PW="${PW_MODULES:-$HOME/.cache/dusu-ri-pwrun/node_modules}"
OUT="${OUT_DIR:-$HOME/.cache/dusu-tk-shots}"
mkdir -p "$OUT"
SPEC="$1"; shift || true
exec docker run --rm --ipc=host --user "$(id -u):$(id -g)" -e HOME=/tmp -e NODE_PATH=/pw/node_modules -e OUT=/out -e REPO=/repo -e VERBOSE -e HTML_SRC -e SECTIONS \
  ${ORIG_HTML_HOST:+-v "$ORIG_HTML_HOST":/orig.html:ro -e ORIG_HTML=/orig.html} \
  -v "$REPO":/repo:ro -v "$PW":/pw/node_modules:ro -v "$OUT":/out -w /repo/tests/talk/browser \
  mcr.microsoft.com/playwright:v1.60.0-noble node "$SPEC" "$@"

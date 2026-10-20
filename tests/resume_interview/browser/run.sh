#!/usr/bin/env bash
# Run one browser spec inside the Playwright image (nothing is installed in the repo, no host port is bound).
#   tests/resume_interview/browser/run.sh smoke.cjs [args...]
# First time only:   mkdir -p ~/.cache/dusu-ri-pwrun && cd ~/.cache/dusu-ri-pwrun && \
#   docker run --rm -v "$PWD":/w -w /w -e npm_config_cache=/w/.npm mcr.microsoft.com/playwright:v1.60.0-noble \
#   bash -lc 'npm init -y >/dev/null; npm i playwright@1.60.0 pngjs@7'
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
PW="${PW_MODULES:-$HOME/.cache/dusu-ri-pwrun/node_modules}"
OUT="${OUT_DIR:-$HOME/.cache/dusu-ri-shots}"
mkdir -p "$OUT"
SPEC="$1"; shift || true
exec docker run --rm --ipc=host --user "$(id -u):$(id -g)" -e HOME=/tmp -e NODE_PATH=/pw/node_modules -e OUT=/out -e REPO=/repo -e WRAP -e VP -e ONLY -e CASES -e VERBOSE \
  ${HTML_SRC_HOST:+-v "$HTML_SRC_HOST":/mutated.html:ro -e HTML_SRC=/mutated.html} \
  ${ORIG_HTML_HOST:+-v "$ORIG_HTML_HOST":/orig.html:ro -e ORIG_HTML=/orig.html} \
  -v "$REPO":/repo:ro -v "$PW":/pw/node_modules:ro -v "$OUT":/out -w /repo/tests/resume_interview/browser \
  mcr.microsoft.com/playwright:v1.60.0-noble node "$SPEC" "$@"

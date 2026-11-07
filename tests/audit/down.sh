#!/usr/bin/env bash
# Stop and remove everything tests/audit/up.sh started.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ -f "$HERE/.out/env" ] || { echo "nothing is up"; exit 0; }
mapfile -t L < "$HERE/.out/env"
docker rm -f "${L[2]}" "${L[1]}" >/dev/null 2>&1 || true
docker network rm "${L[0]}" >/dev/null 2>&1 || true
rm -f "$HERE/.out/env"
echo "audit app removed"

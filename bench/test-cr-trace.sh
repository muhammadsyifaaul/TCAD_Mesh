#!/usr/bin/env bash
set -uo pipefail
export MSYS_NO_PATHCONV=1
PASS=0; FAIL=0
ok()  { echo "  OK  $*"; PASS=$((PASS+1)); }
fail(){ echo "  FAIL $*"; FAIL=$((FAIL+1)); }
PYTHON="python"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "A: before tool loop"
for tool in docker curl; do
  PATH_OF_TOOL=$(command -v "$tool" 2>/dev/null) || PATH_OF_TOOL=""
  if [ -n "$PATH_OF_TOOL" ]; then ok "$tool found: $PATH_OF_TOOL"
  else fail "$tool NOT FOUND"; fi
done
echo "B: after tool loop"

ok "Python: $PYTHON ($(command -v "$PYTHON" 2>/dev/null))"
echo "C: after python ok"

if docker info > /dev/null 2>&1; then ok "Docker daemon running"
else fail "Docker daemon not running"; exit 1; fi
echo "D: after docker info"

if [[ -f .env ]]; then ok ".env file present"
else fail ".env missing"; fi
echo "E: after env check"

echo "PASS=$PASS FAIL=$FAIL"

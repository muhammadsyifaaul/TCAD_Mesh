#!/usr/bin/env bash
set -uo pipefail
export MSYS_NO_PATHCONV=1
PASS=0; FAIL=0
ok()  { echo "  OK  $*"; PASS=$((PASS+1)); }
fail(){ echo "  FAIL $*"; FAIL=$((FAIL+1)); }
echo "step 1 start"
for tool in docker curl; do
  echo "checking $tool"
  PATH_OF_TOOL=$(command -v "$tool" 2>/dev/null) || PATH_OF_TOOL=""
  if [ -n "$PATH_OF_TOOL" ]; then
    ok "$tool found: $PATH_OF_TOOL"
  else
    fail "$tool NOT FOUND"
  fi
done
echo "step 1 done PASS=$PASS FAIL=$FAIL"

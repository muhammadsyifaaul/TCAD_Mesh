#!/usr/bin/env bash
set -uo pipefail
export MSYS_NO_PATHCONV=1
PASS=0
echo "before for"
for tool in docker curl; do
  echo "checking $tool"
  TOOL_PATH=$(command -v "$tool" 2>/dev/null) || TOOL_PATH=""
  echo "  tool=$tool path=$TOOL_PATH"
  PASS=$((PASS+1))
done
echo "after for PASS=$PASS"

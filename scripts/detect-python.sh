#!/usr/bin/env sh
# scripts/detect-python.sh
# Cross-platform Python detection: python3 first, then python.
# Sources this file to get $PYTHON.
# Works on Linux, macOS, and Windows Git Bash.

if command -v python3 > /dev/null 2>&1; then
  PYTHON="python3"
elif command -v python > /dev/null 2>&1; then
  PYTHON="python"
else
  echo "FATAL: Neither python3 nor python found" >&2
  exit 1
fi

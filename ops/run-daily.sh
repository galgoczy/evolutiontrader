#!/bin/bash
# A launchd ezt hívja naponta 02:00-kor. A repó gyökeréből futtatja a napi lépéseket.
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO" || exit 1
mkdir -p logs
UV="${UV_BIN:-$(command -v uv || echo "$HOME/.local/bin/uv")}"
{
  echo "=== $(date '+%Y-%m-%d %H:%M:%S') napi futás ==="
  "$UV" run evolab daily
  echo "=== kilépési kód: $? ==="
} >> "logs/daily.log" 2>&1

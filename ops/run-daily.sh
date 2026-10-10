#!/bin/bash
# A launchd ezt hívja naponta 02:00-kor. A repó gyökeréből futtatja a napi lépéseket.
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
echo "$(date '+%F %T') indul: $REPO"
cd "$REPO" || { echo "Nem érem el a repót (külső lemez / Teljes lemezhozzáférés?)"; exit 1; }
mkdir -p logs || { echo "Nem tudok írni a logs/ mappába"; exit 1; }
UV="${UV_BIN:-$(command -v uv || echo "$HOME/.local/bin/uv")}"
{
  echo "=== $(date '+%Y-%m-%d %H:%M:%S') napi futás ==="
  "$UV" run evolab daily
  echo "=== kilépési kód: $? ==="
} >> "logs/daily.log" 2>&1

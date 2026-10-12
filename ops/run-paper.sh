#!/bin/bash
# A launchd óránként hívja (3 perccel egész óra után): Telegram-parancsok (/approve, /reject),
# Hyperliquid-gyertyák szinkronja + paper-újrajátszás, végül az őr (riasztás Telegramon).
# Idempotens: ha nincs új lezárt gyertya, ugyanazt az eredményt írja újra. Óránkénti futás, mert a
# 4 órás gyertyahatárok UTC-ben vannak, a launchd pedig helyi időben ütemez (nyári/téli időszámítás).
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO" || { echo "$(date '+%F %T') Nem érem el a repót (külső lemez?)"; exit 1; }
mkdir -p logs || exit 1
UV="${UV_BIN:-$(command -v uv || echo "$HOME/.local/bin/uv")}"
{
  echo "=== $(date '+%Y-%m-%d %H:%M:%S') paper ==="
  "$UV" run evolab telegram-poll || echo "Telegram-parancsok: hiba (a paper ettől fut)"
  "$UV" run evolab paper run
  "$UV" run evolab watchdog || echo "őr: hiba"
  echo "=== kilépési kód: $? ==="
} >> "logs/paper.log" 2>&1

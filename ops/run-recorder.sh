#!/bin/bash
# A launchd ezt tartja életben (KeepAlive). A Hyperliquid rögzítőt indítja a repó gyökeréből.
# A napló a launchd-n keresztül a ~/Library/Logs/evolutiontrader/recorder.*.log fájlokba megy.
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO" || { echo "$(date '+%F %T') Nem érem el a repót (külső lemez?)"; sleep 60; exit 1; }
UV="${UV_BIN:-$(command -v uv || echo "$HOME/.local/bin/uv")}"
exec "$UV" run evolab recorder

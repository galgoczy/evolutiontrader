#!/bin/bash
# A launchd folyamatosan futtatja (KeepAlive): a dashboard helyi kiszolgálása 127.0.0.1:8790-en,
# a Cloudflare-tunnel (com.evolutiontrader.tunnel) mögé. Csak a reports/index.html-t adja ki.
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO" || { echo "$(date '+%F %T') Nem érem el a repót (külső lemez?)"; sleep 60; exit 1; }
UV="${UV_BIN:-$(command -v uv || echo "$HOME/.local/bin/uv")}"
exec "$UV" run evolab dashboard-serve --port 8790

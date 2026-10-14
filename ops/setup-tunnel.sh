#!/bin/bash
# A dashboard publikálása Cloudflare-tunnelen: evo.zentopia.hu -> 127.0.0.1:8790.
# Újrafuttatható: a meglévő tunnelt/DNS-rekordot nem hozza létre újra.
# Feltétel: `cloudflared tunnel login` már megtörtént (~/.cloudflared/cert.pem), a zóna a fiókban van.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
NAME="evolab"
HOST="${1:-evo.zentopia.hu}"
CF="$(command -v cloudflared || echo /opt/homebrew/bin/cloudflared)"
CONF="$HOME/.cloudflared/$NAME.yml"

ID="$("$CF" tunnel list --output json 2>/dev/null | python3 -c "import json,sys; print(next((t['id'] for t in json.load(sys.stdin) if t['name']=='$NAME'), ''))")"
if [ -z "$ID" ]; then
  "$CF" tunnel create "$NAME"
  ID="$("$CF" tunnel list --output json | python3 -c "import json,sys; print(next(t['id'] for t in json.load(sys.stdin) if t['name']=='$NAME'))")"
fi
cat > "$CONF" <<YML
# EvolutionTrader dashboard – Cloudflare Tunnel. Csak a dashboardot (127.0.0.1:8790) teszi elérhetővé, minden más 404.
tunnel: $ID
credentials-file: $HOME/.cloudflared/$ID.json
ingress:
  - hostname: $HOST
    service: http://127.0.0.1:8790
  - service: http_status:404
YML
"$CF" tunnel --config "$CONF" ingress validate
"$CF" tunnel route dns "$NAME" "$HOST" || echo "(a DNS-rekord valószínűleg már létezik)"
bash "$REPO/ops/install-launchd.sh" dashboard tunnel
echo "Kész: https://$HOST  (tunnel: $NAME / $ID)"

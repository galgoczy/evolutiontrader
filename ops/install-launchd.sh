#!/bin/bash
# Telepíti (vagy frissíti) a napi 02:00-s launchd feladatot a jelenlegi felhasználónak.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
UV="$(command -v uv || echo "$HOME/.local/bin/uv")"
LABEL="com.evolutiontrader.daily"
DEST="$HOME/Library/LaunchAgents/$LABEL.plist"
# A launchd saját naplója a belső lemezen: ha a külső kötet nem elérhető, itt látszik a hiba oka
LOGDIR="$HOME/Library/Logs/evolutiontrader"
mkdir -p "$HOME/Library/LaunchAgents" "$LOGDIR" "$REPO/logs"

# XML-ben az & jelet escape-elni kell; a sed elválasztója | (a mappanév tartalmazhat /-t)
esc() { printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/|/\\|/g'; }
sed -e "s|__REPO__|$(esc "$REPO")|g" \
    -e "s|__UV__|$(esc "$UV")|g" \
    -e "s|__LOGDIR__|$(esc "$LOGDIR")|g" \
    -e "s|__PATHDIR__|$(esc "$(dirname "$UV")")|g" \
    "$REPO/ops/launchd/$LABEL.plist.template" > "$DEST"
plutil -lint "$DEST"

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$DEST"
echo "Telepítve: $DEST"
echo "launchd napló: $LOGDIR/launchd.err.log"
echo "Kézi próbafuttatás: launchctl kickstart -k gui/$(id -u)/$LABEL"

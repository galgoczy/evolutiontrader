#!/bin/bash
# Telepíti (vagy frissíti) a launchd feladatokat a jelenlegi felhasználónak:
#   com.evolutiontrader.daily     napi 02:00-s futás
#   com.evolutiontrader.recorder  Hyperliquid rögzítő, folyamatosan (KeepAlive)
#   com.evolutiontrader.paper     élő paper, óránként :03-kor
# Csak az egyiket: ops/install-launchd.sh recorder   (vagy: daily)
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
UV="$(command -v uv || echo "$HOME/.local/bin/uv")"
# A launchd saját naplója a belső lemezen: ha a külső kötet nem elérhető, itt látszik a hiba oka
LOGDIR="$HOME/Library/Logs/evolutiontrader"
mkdir -p "$HOME/Library/LaunchAgents" "$LOGDIR" "$REPO/logs"

# XML-ben az & jelet escape-elni kell; a sed elválasztója | (a mappanév tartalmazhat /-t)
esc() { printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/|/\\|/g'; }

install_one() {
    local LABEL="com.evolutiontrader.$1"
    local DEST="$HOME/Library/LaunchAgents/$LABEL.plist"
    sed -e "s|__REPO__|$(esc "$REPO")|g" \
        -e "s|__UV__|$(esc "$UV")|g" \
        -e "s|__LOGDIR__|$(esc "$LOGDIR")|g" \
        -e "s|__PATHDIR__|$(esc "$(dirname "$UV")")|g" \
        "$REPO/ops/launchd/$LABEL.plist.template" > "$DEST"
    plutil -lint "$DEST"
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$DEST"
    echo "Telepítve: $DEST"
}

for job in "${@:-daily recorder paper}"; do
    for j in $job; do install_one "$j"; done
done
echo "launchd naplók: $LOGDIR/"
echo "Napi futás kézi próbája: launchctl kickstart -k gui/$(id -u)/com.evolutiontrader.daily"
echo "Rögzítő állapota:        launchctl print gui/$(id -u)/com.evolutiontrader.recorder | grep state"

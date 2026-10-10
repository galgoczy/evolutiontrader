#!/bin/bash
# Eltávolítja a launchd feladatokat. Csak az egyiket: ops/uninstall-launchd.sh recorder
for j in ${@:-daily recorder}; do
    LABEL="com.evolutiontrader.$j"
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
    echo "Eltávolítva: $LABEL"
done

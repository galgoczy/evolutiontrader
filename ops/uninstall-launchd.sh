#!/bin/bash
LABEL="com.evolutiontrader.daily"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
echo "Eltávolítva: $LABEL"

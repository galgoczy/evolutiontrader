#!/bin/bash
# EvolutionTrader - 0. fázis telepítés a Mac minin. Többször is futtatható.
# Használat (a repó mappájából):  bash scripts/setup-mac.sh
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"
say() { printf '\n\033[1;34m== %s ==\033[0m\n' "$1"; }
ok()  { printf '\033[1;32m✔ %s\033[0m\n' "$1"; }

say "1/7 Fejlesztői eszközök (git, make)"
if ! xcode-select -p >/dev/null 2>&1; then
  echo "Hiányzik az Xcode Command Line Tools. Most megnyílik a telepítő ablak."
  echo "Ha kész, futtasd újra ezt a szkriptet."
  xcode-select --install || true
  exit 1
fi
ok "git és make megvan"

say "2/7 uv (Python csomagkezelő)"
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
ok "uv $(uv --version | awk '{print $2}')"

say "3/7 Python 3.12 és függőségek"
uv python install 3.12
uv sync
ok "függőségek telepítve"

say "4/7 .env (titkok)"
if [ ! -f .env ]; then cp .env.example .env; ok ".env létrehozva"; else ok ".env már létezik"; fi
setenv() {  # setenv KULCS ERTEK  -> beírja/lecseréli a .env-ben
  local key="$1" val="$2"
  if grep -q "^$key=" .env; then
    sed -i '' "s|^$key=.*|$key=$val|" .env
  else
    echo "$key=$val" >> .env
  fi
}
getenv() { grep "^$1=" .env | head -1 | cut -d= -f2- || true; }

say "5/7 Adatbázis és tesztek"
uv run evolab --version
uv run evolab init-db
uv run pytest
ok "DB kész, tesztek zöldek"

say "6/7 Telegram"
if [ -z "$(getenv TELEGRAM_BOT_TOKEN)" ]; then
  echo "Telegramban nyisd meg a @BotFather-t, küldd: /newbot, adj nevet, és másold ide a kapott tokent."
  read -r -p "Bot token (Enter = kihagyás most): " TOKEN
  if [ -n "$TOKEN" ]; then setenv TELEGRAM_BOT_TOKEN "$TOKEN"; ok "token mentve"; fi
fi
if [ -n "$(getenv TELEGRAM_BOT_TOKEN)" ] && [ -z "$(getenv TELEGRAM_CHAT_ID)" ]; then
  echo "Most nyisd meg a saját botodat a Telegramban, nyomd meg a Start gombot / írj neki bármit."
  read -r -p "Ha megvan, nyomj Entert... " _
  CHAT_ID="$(uv run evolab telegram-chatid | grep '^TELEGRAM_CHAT_ID=' | head -1 | cut -d= -f2 | awk '{print $1}')"
  if [ -n "$CHAT_ID" ]; then setenv TELEGRAM_CHAT_ID "$CHAT_ID"; ok "chat id mentve: $CHAT_ID"
  else echo "Nem találtam üzenetet a botnál. Futtasd újra a szkriptet, miután írtál neki."; fi
fi
if [ -n "$(getenv TELEGRAM_CHAT_ID)" ]; then
  uv run evolab telegram-ping && ok "Telegram üzenet elküldve, nézd meg a telefonod"
else
  echo "Telegram kihagyva. Később: futtasd újra ezt a szkriptet."
fi

say "7/7 Napi ütemezés (launchd, 02:00)"
read -r -p "Telepítsem a napi 02:00-s futást? [i/N] " ANS
if [[ "$ANS" =~ ^[iIyY] ]]; then
  bash ops/install-launchd.sh
  ok "ütemezés telepítve"
else
  echo "Kihagyva. Később: bash ops/install-launchd.sh"
fi

say "Kész"
uv run evolab status
echo
echo "0. fázis teljes ellenőrzése bármikor:  make verify-0"

# EvolutionTrader - fázis-ellenőrzések. Használat: make verify-0
.PHONY: help setup test verify-0 verify-1 status ping daily data recorder-install

help:
	@echo "make setup     - függőségek telepítése (uv sync)"
	@echo "make test      - tesztek futtatása"
	@echo "make verify-0  - 0. fázis elfogadási ellenőrzés"
	@echo "make verify-1  - 1. fázis (adat) elfogadási ellenőrzés"
	@echo "make data      - Binance adat frissítése + rezsimcímkék"
	@echo "make recorder-install - Hyperliquid rögzítő launchd-telepítése"
	@echo "make status    - állapot"
	@echo "make ping      - Telegram tesztüzenet"
	@echo "make daily     - napi futás kézzel"

setup:
	uv sync

test:
	uv run pytest

status:
	uv run evolab status

ping:
	uv run evolab telegram-ping

daily:
	uv run evolab daily

data:
	uv run evolab data update
	uv run evolab regime

recorder-install:
	bash ops/install-launchd.sh recorder

verify-0:
	@echo "== 1/4 verzió =="
	uv run evolab --version
	@echo "== 2/4 adatbázis =="
	uv run evolab init-db
	@echo "== 3/4 tesztek =="
	uv run pytest
	@echo "== 4/4 Telegram =="
	uv run evolab telegram-ping --text "EvolutionTrader: 0. fázis ellenőrzés OK ✅"
	@echo "== 0. fázis: KÉSZ =="

verify-1:
	@echo "== 1/5 tesztek =="
	uv run pytest
	@echo "== 2/5 Binance adat frissítése (csak a hiányzó) =="
	uv run evolab data update
	@echo "== 3/5 rezsimcímkék =="
	uv run evolab regime > /dev/null
	@echo "== 4/5 hiányriport =="
	-uv run evolab data gaps
	@echo "== 5/5 adatminőség, checksum, regime_daily, rögzítő =="
	uv run evolab data check
	@echo "== 1. fázis: KÉSZ =="

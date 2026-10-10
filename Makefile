# EvolutionTrader - fázis-ellenőrzések. Használat: make verify-0
.PHONY: help setup test verify-0 status ping daily

help:
	@echo "make setup     - függőségek telepítése (uv sync)"
	@echo "make test      - tesztek futtatása"
	@echo "make verify-0  - 0. fázis elfogadási ellenőrzés"
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

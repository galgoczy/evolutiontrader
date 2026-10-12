# EvolutionTrader - fázis-ellenőrzések. Használat: make verify-0
.PHONY: help setup test verify-0 verify-1 verify-2 verify-3 verify-4 verify-5 status ping daily data recorder-install

help:
	@echo "make setup     - függőségek telepítése (uv sync)"
	@echo "make test      - tesztek futtatása"
	@echo "make verify-0  - 0. fázis elfogadási ellenőrzés"
	@echo "make verify-1  - 1. fázis (adat) elfogadási ellenőrzés"
	@echo "make verify-2  - 2. fázis (szimulátor + 1 stratégia) elfogadási ellenőrzés"
	@echo "make verify-3  - 3. fázis (bíró) elfogadási ellenőrzés"
	@echo "make verify-4  - 4. fázis (induló populáció, L1-ítéletek) elfogadási ellenőrzés"
	@echo "make verify-5  - 5. fázis (élő paper, riport, dashboard) elfogadási ellenőrzés"
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

verify-2:
	@echo "== 1/4 szimulátor-tesztek (test_sim_*) =="
	uv run pytest -v -k "sim_" tests/test_phase2.py
	@echo "== 2/4 összes teszt (lookahead is) =="
	uv run pytest
	@echo "== 3/4 visszateszt: trend-ema-cross-4h-01 (valódi adat, holdout nélkül) =="
	uv run evolab backtest --strategy trend-ema-cross-4h-01
	@echo "== 4/4 kimeneti parquet fájlok és ledger-sor =="
	uv run python -c "from evolab.config import load_config; from evolab.db import connect; \
	import pandas as pd, pathlib; cfg = load_config(); \
	r = connect(cfg.db_path).execute('SELECT trial_id, strategy_id, judge_version, created_at FROM trials ORDER BY created_at DESC LIMIT 1').fetchone(); \
	print('ledger:', dict(r)); d = cfg.path('data') / 'backtests' / r['strategy_id'] / r['trial_id']; \
	[print(f'  {p.name:<17} {len(pd.read_parquet(p)):>7} sor') for p in sorted(d.glob('*.parquet'))]"
	@echo "== 2. fázis: KÉSZ =="

verify-3:
	@echo "== 1/4 bíró-, ledger- és holdout-tesztek =="
	uv run pytest -v -k "judge or ledger or holdout" tests/
	@echo "== 2/4 összes teszt =="
	uv run pytest
	@echo "== 3/4 védett fájlok: a judge.yaml változatlan (verzió + changelog) =="
	uv run python -c "from evolab.config import load_config; c = load_config(); print('judge.yaml verzió:', c.judge_version); [print('  ', e) for e in c.judge['changelog']]"
	@echo "== 4/4 teljes L1 ítélet egy variánsra, időméréssel (< 2 perc) =="
	/usr/bin/time -p uv run evolab judge --strategy trend-ema-cross-4h-01
	@echo "== 3. fázis: KÉSZ =="

verify-4:
	@echo "== 1/3 tesztek (populáció, lookahead mind a 40 variánsra) =="
	uv run pytest
	@echo "== 2/3 induló populáció: alapfuttatás + L1-ítélet minden variánsra =="
	uv run evolab population seed
	@echo "== 3/3 ledger: ítéletek és kísérletek száma =="
	uv run python -c "from evolab.config import load_config; from evolab.db import connect; \
	c = connect(load_config().db_path); \
	[print(f'  {k or \"-\":<16} {n:>5}') for k, n in c.execute('SELECT gate_result, COUNT(*) FROM trials GROUP BY 1 ORDER BY 2 DESC')]"
	@echo "== 4. fázis: KÉSZ =="

verify-5:
	@echo "== 1/5 tesztek (test_paper_equals_backtest is) =="
	uv run pytest
	@echo "== 2/5 launchd: rögzítő, paper (óránként), napi futás =="
	@launchctl list | grep evolutiontrader || echo "HIBA: nincs launchd feladat (ops/install-launchd.sh)"
	@tail -n 3 logs/paper.log 2>/dev/null || echo "még nincs paper-napló"
	@echo "== 3/5 paper-kör (Hyperliquid-szinkron + újrajátszás) =="
	uv run evolab paper run
	@echo "== 4/5 paper vs. visszateszt egyezés + mért slippage (a 30 napos ellenőrzés addig napi) =="
	uv run evolab paper status
	@echo "== 5/5 napi riport + dashboard =="
	uv run evolab report
	@echo "== 5. fázis: KÉSZ (a végleges paper = visszateszt ellenőrzés 30 nap paper után) =="

# Állapot

| Fázis | Állapot | Megjegyzés |
|---|---|---|
| 0 Váz | **kész** (2026-10-10) | `make verify-0` zöld a Mac minin; launchd napi futás 0-s kóddal, Telegram OK |
| 1 Adat | **kész** (2026-10-11) | `make verify-1` zöld: hiány 0, checksum OK, `regime_daily` 13 103 sor, rögzítő 24 órája fut 99,9%-os lefedettséggel |
| 2 Szimulátor + 1 stratégia | **kész** (2026-10-11) | `make verify-2` zöld; PR #3 merge-ölve |
| 3 Bíró | **kész** (2026-10-11) | `make verify-3` zöld; PR #4 merge-ölve (emberi jóváhagyással) |
| 4 Induló populáció | **kész** (2026-10-11) | `make verify-4` zöld; 40 variáns ítélettel, 0 ment át L1-en; PR #5 |
| 5 Élő paper | nem kezdődött | |
| 6 Hurok | nem kezdődött | |
| 7 Stabilizálás | nem kezdődött | |

## 0. fázis – mi készült
- `pyproject.toml` (uv, Python 3.12), `config/{lab,judge,families}.yaml`, `db/schema.sql` (append-only `trials` és `ladder_events`).
- `evolab` CLI: `--version`, `init-db`, `status`, `telegram-ping`, `telegram-chatid`, `daily` (0. fázisban csak szívverés).
- `ops/`: launchd sablon + telepítő, napi futtató szkript (`logs/daily.log`).
- Tesztek: `tests/test_phase0.py` (config, DB idempotens, ledger append-only, daily, status, verzió).

## 0. fázis – lezárás (2026-10-10)
- `uv.lock` commitolva.
- `make verify-0` zöld a Mac minin (6 teszt, Telegram ping elküldve); kimenet a PR #1 leírásában.
- launchd napi futás (02:00) lefutott 0-s kilépési kóddal.

## 1. fázis – mi készült (2026-10-10)
- `evolab data update` (`data/binance_bulk.py`): havi zipek (klines, markPriceKlines, premiumIndexKlines 1h/4h/1d, fundingRate, plusz OI a `metrics` fájlokból) a data.binance.vision-ről, mindegyik `.CHECKSUM`-mal ellenőrizve; az aktuális hónap a `daily/` útvonalról, a legutolsó órák és az archívum lyukai a REST API-ból. Coinonként az első elérhető hónaptól. Fejléc nélküli és fejléces CSV, ms/µs időbélyeg kezelve. Idempotens: újrafuttatáskor csak a hiányzó zip töltődik le.
- `evolab data gaps` / `evolab data check`: hiányriport coinonként és idősíkonként (`reports/data_gaps.csv`), ismert leállások külön (`docs/DONTESEK.md` „Ismert Binance-leállások”).
- `evolab recorder` (`live/recorder.py`): Hyperliquid `metaAndAssetCtxs` percenként JSONL-pufferbe, óránként napi parquetbe; 4 óránként HL-gyertyák és funding. Külön launchd agent (`com.evolutiontrader.recorder`, KeepAlive), napló: `~/Library/Logs/evolutiontrader/recorder.*.log`.
- `evolab regime` (`features/regime.py`): trend / vol / pozícionáltság a spec 2.4 szerint a `regime_daily` táblába; `tests/test_no_lookahead.py` rezsim- és indikátor-része.
- A napi futás `data` lépése valódi: Binance-pótlás + rezsimcímkék.

## 1. fázis – adat (2026-10-10)
- 6 coin × 3 idősík: 0 hiányzó gyertya; 1 dokumentált leállás (2024-10-28 20:00 UTC, mind a 6 coin).
- 16 236 zip, mind checksum OK.
- `regime_daily`: 13 097 sor, mind a 9 trend×vol kombináció előfordul.

## 1. fázis – lezárás (2026-10-11)
- `make verify-1` zöld a Mac minin (03:16): 38 teszt zöld (1 xfail: stratégiajel, 2. fázis), 0 hiányzó gyertya, 16 296/16 296 zip checksum OK, `regime_daily` 13 103 sor (9/9 trend×vol kombináció), rögzítő 24,3 órája fut, 1439/1440 perc (99,9%), napló hibamentes.
- A 02:00-s napi futás már a valódi `data` lépéssel ment (új napi zipek letöltve).
- Kimenet a PR #2 leírásában.

## 2. fázis – mi készült (2026-10-11)
- `strategy/base.py` (sablon: BarFrame, RegimeFrame előző napi címkével, SignalFrame), `strategy/registry.py` (YAML fejléc ellenőrzése, hypothesis ≥ 200 karakter).
- Első variáns: `strategy/families/trend/ema_cross_4h_01.py` (EMA 20/100, ATR-követő stop).
- `sim/`: `engine.py` (portfólió-szimulátor: következő nyitón teljesülés, stop/TP konzervatív sorrenddel, mark áras equity), `costs.py` (taker díj + ATR-arányos slippage, költségszorzó), `funding.py`, `risk.py` (vol-cél, 2x bruttó, 50%/coin, megszakítók).
- `evolab backtest --strategy <id>`: holdout-ablak kizárva, `trades/equity/exposure/events` parquet, `trials` sor.
- Tesztek: `test_sim_known_answer` (5 kézzel számolt kötés díjjal és fundinggal), `test_sim_deterministic`, stop/rés/plafon/megszakítók, registry, `test_no_lookahead` stratégia-része (minden regisztrált variánsra).

## 2. fázis – első visszateszt (2026-10-11, tájékoztató, nem bírói ítélet)
- `trend-ema-cross-4h-01`, 2020-01 – 2026-04 (holdout kizárva): 957 kötés, +33,1%, max DD 7,0% (mark), PF 1,25, díj 520 USD, funding −351 USD, 139 megszakító-szünet, státusz ok.

## 3. fázis – mi készült (2026-10-11)
- `judge/` (VÉDETT): `metrics.py`, `walkforward.py`, `cpcv.py`, `pbo.py`, `dsr.py`, `ledger.py`, `gates.py`, `holdout.py`, `evaluate.py`. A `config/judge.yaml` változatlan (1-es verzió).
- Holdout-izoláció a tár szintjén (`store.holdout_locked`).
- `evolab judge --strategy <id>`: teljes L1 ítélet (1x/2x/3x költség, walk-forward, paraméter-stabilitás, PBO, DSR, kapuk), egy ledger-sor; `--holdout`: egyszeri holdout-futás burn-szabállyal.
- Tesztek: `test_judge_rejects_overfit`, `test_judge_accepts_simple`, `test_judge_rejects_random_walk`, `test_holdout_isolation`, holdout egyszeri/burn, DSR/PBO/CPCV/walk-forward/kapuk egységtesztek.

## 3. fázis – első ítélet (2026-10-11)
- `trend-ema-cross-4h-01`: **FAIL** 4 mp alatt. Bukott kapuk: PF 2x költségnél 1,07 (< 1,3), OOS/IS −0,01 (< 0,5), DSR 0,938 (≤ 0,95), PBO nem számolható (1 variáns a családban). Átment: kötésszám 957, max DD 7%, 5 pozitív rezsim, paraméter-stabilitás.

## 4. fázis – induló populáció (2026-10-11)
- 40 variáns az 5 családból (`strategy/families/`), közös jelépítőkkel (`strategy/lib.py`); a BarFrame-ben OI is van.
- `evolab population seed|report`: alapfuttatás + L1-ítélet minden variánsra, riport `reports/phase4_l1.md`.
- Eredmény: **0/40 ment át L1-en** (trend 0/14, volbreak 0/6, relstrength 0/6, positioning 0/8, rangerev 0/6).
  - Legközelebb: `volbreak-squeeze-4h-04` – csak a „PF 2x költségnél ≥ 1,3” kapun bukik (1,20); DSR 0,98, PBO 0,04, OOS/IS 1,07, max DD 8,6%.
  - A trend-család 4h EMA-variánsai 1x költségnél nyereségesek (PF 1,1–1,25), de 2x költségnél ~1,0, és a DSR 0,6 körül.
  - A rangerev, relstrength és a kontrariánus pozícionáltság egyértelműen veszteséges.
- A modellezett slippage a díj 2,5–2,9-szerese (az ATR-arányos tag miatt): a költségmodell a legerősebb tényező.

## Döntések és nyitott kérdés (2026-10-11)
1. „2x költség” kapu: díj + slippage duplázva – **eldöntve, marad**.
2. Slippage-modell: változatlan, az 5. fázis paper-mérése után újra – **eldöntve**.
3. Rezsim-kapu kötésszám-minimuma: **nyitott**. Újra elő kerül, ha egy variáns csak egy vékony (< 10 kötéses) pozitív kombináció miatt menne át a rezsim-kapun (a riport `regimes_pos_min10` oszlopa figyeli).

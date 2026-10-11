# Állapot

| Fázis | Állapot | Megjegyzés |
|---|---|---|
| 0 Váz | **kész** (2026-10-10) | `make verify-0` zöld a Mac minin; launchd napi futás 0-s kóddal, Telegram OK |
| 1 Adat | **kész** (2026-10-11) | `make verify-1` zöld: hiány 0, checksum OK, `regime_daily` 13 103 sor, rögzítő 24 órája fut 99,9%-os lefedettséggel |
| 2 Szimulátor + 1 stratégia | nem kezdődött | |
| 3 Bíró | nem kezdődött | |
| 4 Induló populáció | nem kezdődött | |
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

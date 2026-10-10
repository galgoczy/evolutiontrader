# Állapot

| Fázis | Állapot | Megjegyzés |
|---|---|---|
| 0 Váz | **kész** (2026-10-10) | `make verify-0` zöld a Mac minin; launchd napi futás 0-s kóddal, Telegram OK |
| 1 Adat | nem kezdődött | |
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

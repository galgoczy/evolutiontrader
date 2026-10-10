# EvolutionTrader – munkarend Claude Code-nak

Olvasd el először: `docs/01-koncepcio.md` (mit és miért), `docs/02-specifikacio.md` (hogyan), `docs/STATUS.md` (hol tartunk).

## Alapelvek (spec 0. fejezet)
1. **A bíró szent.** `src/evolab/judge/` és `config/judge.yaml` csak dátumozott, emberi jóváhagyású változtatással módosulhat (`version` emelés + `changelog`). LLM-kutató és -fejlesztő sosem írja.
2. **Egy kód, két mód.** Ugyanaz a szimulátor visszatesztben és paperben.
3. **Minden kísérlet naplózva** a `trials` táblába, a bukottak is. A tábla csak beszúrható.
4. **Nincs lookahead.** Jel a gyertya zárásán, teljesülés a következő nyitón; rezsimcímke az előző napé.
5. **Kicsi, olvasható kód.** Pandas/NumPy/DuckDB, nincs nehéz keretrendszer.
6. **Fázisonként ellenőrizhető:** `make verify-N`.

## Védett fájlok
- `config/judge.yaml`
- `src/evolab/judge/**`
- `src/evolab/sim/**` (az `evolve/H-*` ágakon tilos módosítani)
- `db/schema.sql` append-only triggerei

## Munkamenet
- Egy fázis = egy PR. A PR leírásában a `make verify-N` kimenete.
- Tesztek mindig zöldek; ha egy teszt a fázis miatt még nem futtatható: `xfail` okkal, nem törlés.
- Minden olyan döntést, ami a specben nincs leírva, írj a `docs/DONTESEK.md` naplóba (dátum, döntés, indok).
- Fázis végén frissítsd a `docs/STATUS.md`-t.
- `data/`, `reports/`, `logs/`, `.env` nincs gitben.

## Parancsok
- `uv sync` – függőségek
- `uv run pytest` – tesztek
- `uv run evolab status` – állapot
- `make verify-0` … `make verify-7` – fázis-ellenőrzések

## Környezet
Mac mini, 24/7, a repó egy külső köteten: `/Volumes/Mac Nvme Extended/Github/evolutiontrader` (szóköz van az útvonalban: mindig idézőjelezd). Ütemezés: launchd (`ops/install-launchd.sh`), napi 02:00.
A felhasználó nem programozó: magyarul, röviden, a teendőket másolható parancsokkal kommunikáld.

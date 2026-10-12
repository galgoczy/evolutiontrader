# evolutiontrader

Evolúciós paper-trading laboratórium: egy populációnyi szabályalapú kripto-stratégia versenyez ugyanazon az élő adaton, hetente kiértékelve, az AI hipotéziseket és kódot ír, a bíró (kód) dönt.

- [docs/01-koncepcio.md](docs/01-koncepcio.md) – koncepció, kutatási összefoglaló, piacválasztás, mutatók, evolúciós hurok, előléptetési létra, nyitott kérdések
- [docs/02-specifikacio.md](docs/02-specifikacio.md) – technikai specifikáció Claude Code-nak: repó-szerkezet, adat, stratégiasablon, szimulátor, bíró, napi hurok, tesztek, fázisok

- [docs/UZEMELTETES.md](docs/UZEMELTETES.md) – **üzemeltetési útmutató**: mi fut magától, Telegram-parancsok (`/approve`), dashboard, vészleállítás, hibaelhárítás

## Hogyan működik (röviden)

1. **Adat:** Binance-történet (2020-tól) és élő Hyperliquid-rögzítés (percenként).
2. **Populáció:** stratégia-variánsok 5 családban (`src/evolab/strategy/families/`).
3. **Bíró** (kód, `src/evolab/judge/`): visszateszt költséggel és fundinggal, walk-forward, CPCV/PBO, deflated Sharpe, rezsim- és paraméter-stabilitás; minden kísérlet a csak beszúrható ledgerbe.
4. **Létra:** L0 → L1 (bíró) → L2 élő paper → L3 mikro-éles; L1 fölött csak emberi jóváhagyással.
5. **Napi hurok:** a kutató (Claude) hipotéziseket javasol, a fejlesztő (Claude Code, homokozóban) variánst ír, a bíró ítél.

## Indítás a Mac minin

```bash
cd "/Volumes/Mac Nvme Extended/Github/evolutiontrader"
bash scripts/setup-mac.sh
make verify-0
```

Teljes ellenőrzés: `make verify-all`.

Állapot: [`docs/STATUS.md`](docs/STATUS.md) · Döntésnapló: [`docs/DONTESEK.md`](docs/DONTESEK.md) · Claude Code munkarend: [`CLAUDE.md`](CLAUDE.md)

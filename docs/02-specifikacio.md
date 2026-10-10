# EvolutionTrader – technikai specifikáció Claude Code-nak

*1. változat, 2026-10-10. Előfeltétel: `docs/01-koncepcio.md` (3. változat). Ez a dokumentum a „hogyan”. Minden döntés, ami a koncepcióban szerepel, itt kötelező; ami itt nincs leírva, azt Claude Code a legegyszerűbb működő megoldással tölti ki, és a döntést a `docs/DONTESEK.md` naplóba írja.*

---

## 0. Alapelvek a fejlesztőnek

1. **A bíró szent.** A `judge/` csomagban lévő képletek, küszöbök és a holdout-határ csak a `config/judge.yaml` explicit, dátumozott módosításával változhatnak. Az LLM-rétegek (kutató, fejlesztő) sosem írnak ide. Tesztek védik.
2. **Egy kód, két mód.** A szimulátor ugyanaz a kód visszatesztben és élő paperben. Ha a kettő ugyanarra az időszakra 5%-nál jobban eltér, az hiba, nem „piaci zaj”.
3. **Minden kísérlet naplózva.** Nincs olyan visszateszt, ami nem ír a `trials` táblába. A bukott is. Ez a deflated Sharpe bemenete.
4. **Nincs lookahead.** Minden indikátor és rezsimcímke csak a saját gyertyájáig látó adatból számolódik. Teszt bizonyítja: egy jövőbeli gyertya megváltoztatása nem változtathat egy múltbeli jelet.
5. **Kicsi, olvasható kód.** Nincs keretrendszer-függőség, ami 10 ezer sort hoz be egy 200 soros feladatért. Pandas/NumPy/DuckDB elég.
6. **Fázisonként ellenőrizhető.** Minden fázis végén van egy `make verify-N` parancs, ami kimenettel bizonyítja a fázis sikerét.

---

## 1. Technológia és repó-szerkezet

- Python 3.12, `uv` csomagkezelő, `pyproject.toml`.
- Adat: parquet fájlok + DuckDB lekérdezés. Állapot (populáció, kísérletek, kötések): SQLite egy fájlban (`data/lab.db`), a séma `db/schema.sql`-ben.
- Könyvtárak: `pandas`, `numpy`, `duckdb`, `pyarrow`, `ccxt` (csak Binance nyilvános adat), `hyperliquid-python-sdk` (élő ár, funding, később végrehajtás), `scipy` (statisztika), `hmmlearn` (HMM rezsim, 2. fázistól), `pyyaml`, `pydantic`, `anthropic` (kutató), `python-telegram-bot`, `pytest`.
- Ütemezés: `launchd` plist a Mac minin (`ops/launchd/`), napi 02:00 helyi idő. Alternatíva: pm2 `ecosystem.config.cjs` (már használt a gépen).

```
evolutiontrader/
  config/
    lab.yaml           univerzum, idősíkok, költségmodell, populációméret
    judge.yaml         kapuk, küszöbök, holdout, DSR/PBO paraméterek  (VÉDETT)
    families.yaml      stratégiacsaládok, priorok, induló variánsszám
  src/evolab/
    data/              binance_bulk.py, hyperliquid_live.py, store.py, universe.py
    features/          indicators.py (EMA, ATR, Bollinger, ADX, realizált vol), regime.py
    strategy/          base.py (sablon), registry.py, families/<csalad>/<variáns>.py
    sim/               engine.py (portfólió-szimulátor), costs.py, funding.py, risk.py
    judge/             metrics.py, dsr.py, pbo.py, cpcv.py, walkforward.py, gates.py, ledger.py
    evolve/            researcher.py (Claude-hívás), developer.py (Claude Code indítás), mutations.py, population.py, ladder.py
    live/              paper_runner.py, recorder.py, (később) executor.py
    report/            daily.py, dashboard/ (statikus HTML)
    notify/            telegram.py
    cli.py             `evolab` parancs
  db/schema.sql
  tests/
  ops/launchd/, ops/Makefile
  docs/
  data/                (gitben nincs) parquet + lab.db
```

---

## 2. Adat

### 2.1 Univerzum és idősík (`config/lab.yaml`)
```yaml
universe: [BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, XRPUSDT, DOGEUSDT]
timeframes: [1h, 4h, 1d]
history_start: "2020-01-01"     # Binance USDT-M perpetual; amelyik coinnak később indul, onnantól
holdout_months: 6               # gördülő, a futás napjától visszafelé
```

### 2.2 Történelmi adat: Binance nyilvános adattár
- Forrás: `https://data.binance.vision/data/futures/um/monthly/klines/<SYMBOL>/<TF>/<SYMBOL>-<TF>-<YYYY-MM>.zip` és ugyanez `markPriceKlines`, `premiumIndexKlines`, `fundingRate` típusokra. Minden zip mellett `.CHECKSUM` fájl: letöltés után ellenőrizni kell.
- A havi fájlok után a hiányzó napokat a `daily/` útvonalról, az utolsó 1-2 napot CCXT-vel (`binanceusdm.fetch_ohlcv`) pótolja.
- Tárolás: `data/binance/<symbol>/<tf>.parquet`, oszlopok: `ts` (UTC, ms), `open, high, low, close, volume, quote_volume, trades`, plusz 8 órás `funding_rate` a saját parquetjében, `mark_close` a mark-gyertyából.
- Gyertya-időbélyeg: a gyertya **nyitó** ideje. Jel csak a gyertya **zárása után** keletkezhet, és a következő gyertya nyitásán teljesül.
- 2025-01-01-től a Binance spot mikroszekundumot ad; a futures adatnál is ellenőrizni kell az egységet, és ms-re normalizálni.

### 2.3 Élő adat: Hyperliquid
- Nyilvános `POST https://api.hyperliquid.xyz/info` végpont kulcs nélkül: `candleSnapshot` (gyertyák), `fundingHistory`, `metaAndAssetCtxs` (funding, open interest, mark ár, mid ár).
- A `recorder.py` 1 percenként menti minden univerzum-coin mark/mid árát, OI-ját és aktuális fundingját `data/hl/<symbol>/ticks_<YYYY-MM-DD>.parquet`-be, és 4 óránként a lezárt gyertyákat.
- Ez a rögzítő az első naptól fut, függetlenül attól, hogy a többi modul kész-e.

### 2.4 Rezsimcímke (`features/regime.py`)
Napi felbontáson, minden coinra és a BTC-re mint piaci referenciára, három tengely, mindegyik csak múltbeli adatból:

| Tengely | Számítás | Címkék |
|---|---|---|
| trend | close vs. EMA(50) és EMA(200), plusz ADX(14) napi | `up`, `down`, `flat` (ADX < 20 → flat) |
| vol | 30 napos realizált volatilitás percentilise az elmúlt 365 naphoz képest | `low` (<33), `mid`, `high` (>67) |
| pozícionáltság | aktuális funding 30 napos z-score; OI 7 napos változása | `crowded_long`, `crowded_short`, `neutral` |

Kimenet: `regime_daily` tábla (`date, symbol, trend, vol, positioning`). A „két különböző rezsim” kapu a `trend × vol` kombinációt számolja (9 lehetséges), és legalább 2 különböző kombinációban kell pozitív várható érték.

2. fázistól egy HMM-alapú (4 állapot, napi hozam + vol bemenet, walk-forward újraillesztés 30 naponta) címkéző is készül **variánsként**, és a bíró eldönti, melyik címke mellett jobb a populáció. Az LLM-címkézés nem bemenet, csak a kutatói riport szöveges része.

---

## 3. Stratégiasablon (`strategy/base.py`)

Ez az egyetlen felület, amit a fejlesztő LLM kitölt. Vektorizált: a teljes idősorra egyszerre számol, nem gyertyánként ciklusoz.

```python
class Strategy(Protocol):
    meta: StrategyMeta          # id, family, parent_id, hypothesis_id, params, timeframe, created_at
    def signals(self, bars: BarFrame, regime: RegimeFrame) -> SignalFrame: ...
```

- `BarFrame`: multi-index (symbol, ts) DataFrame OHLCV + funding + mark oszlopokkal, az adott idősíkon.
- `RegimeFrame`: napi címkék, a stratégia időbélyegére igazítva úgy, hogy az adott gyertyához az **előző nap** címkéje tartozik (lookahead-védelem).
- `SignalFrame`: oszlopok `target_position` ∈ {-1, 0, +1} szorozva méret-szorzóval (0..1), `stop_price` (opcionális), `take_profit_price` (opcionális), `reason` (rövid string a naplónak). A pozíció a **következő** gyertya nyitóján lép életbe.
- A sablon nem tartalmaz kockázatkezelést: a méretezést, tőkeáttét-limitet, megszakítókat a szimulátor `risk.py` modulja végzi, minden stratégiára egyformán. Így a variánsok csak a jelben különböznek.
- Minden stratégiafájl fejléce egy YAML-blokk: `family`, `hypothesis` (szöveg, miért kellene működnie), `expected_regimes`, `falsifier` (mi cáfolná). A registry elutasítja a fájlt, ha a `hypothesis` üres vagy 200 karakternél rövidebb.

### 3.1 Induló családok (`config/families.yaml`)

| Család | Induló variáns | Mag-ötlet | Prior |
|---|---|---|---|
| `trend` | 14 | EMA-kereszt, Donchian-kitörés, idősoros momentum (20/60/120 gyertya lookback), ATR-trailing kilépés; 4h és 1h | magas |
| `volbreak` | 6 | Bollinger-szűkülés (sávszélesség percentilis < 20) utáni kitörés, ATR-stop | alacsony |
| `relstrength` | 6 | ETH/BTC, SOL/ETH arány z-score-ja, átlaghoz visszatérés long/short lábbal | alacsony |
| `positioning` | 8 | funding z-score és OI-változás mint **szűrő** a trend-jeleken (tiltás crowded irányban), plusz 2 önálló kontrariánus variáns | közepes szűrőként, alacsony önállóan |
| `rangerev` | 6 | Bollinger-visszatérés, csak `trend=flat` címke alatt aktív | alacsony |
| **összesen** | **40** | + 10 hely a kutató első heti hipotéziseinek | |

Minden variáns a teljes univerzumon fut egy portfólióként, egyenlő kockázati súllyal coinonként.

---

## 4. Szimulátor (`sim/`)

Portfólió-szintű, gyertyánként lépő elszámolás, vektorizált előkészítéssel.

- **Teljesülés:** a jel a gyertya zárásán születik, a következő nyitón teljesül, taker díjjal és slippage-dzsel. Stop és take-profit a gyertyán belül a high/low érintésekor teljesül, konzervatív sorrenddel (ha egy gyertyában a stop és a TP is érintett, a stop számít).
- **Költségmodell (`config/lab.yaml`):** taker 0,045%, maker 0,015% (nem használjuk induláskor, minden taker), slippage 0,02% alap + ATR-arányos komponens, funding 8 óránként a pozíció névértékére a tényleges rögzített ráta szerint, mark áron.
- **Mark vs. last:** a PnL és a likvidáció mark áron, a teljesülés last (gyertya) áron.
- **Méretezés (`risk.py`):** volatilitás-cél: minden coin-pozíció úgy skálázva, hogy a 30 napos realizált vol alapján napi 1% portfólió-kockázatot adjon, maximum 2x bruttó tőkeáttét a portfólió szintjén, maximum 50% egy coinon.
- **Megszakítók:** 3 egymást követő vesztes kötés → 24 óra szünet; napi DD 5% → 24 óra; heti DD 10% → a futás „failed” státusszal leáll (ez bukás a bírónál).
- **Kimenet:** `trades` (belépés, kilépés, irány, méret, ár, díj, funding, PnL, reason, regime a belépéskor), `equity` (gyertyánként), `exposure`.
- **Determinisztikus:** ugyanaz a bemenet mindig ugyanazt adja; a teszt ezt ellenőrzi hash-sel.

**Élő paper mód (`live/paper_runner.py`):** 4 óránként (gyertyazárás után 1 perccel) betölti a Hyperliquid lezárt gyertyát és fundingot, lefuttatja minden L2+ stratégia `signals()`-át a rögzített sorra, és a következő gyertya nyitó árán (Hyperliquid mid + slippage) könyveli a változást ugyanazzal az `engine.py`-jal. Ugyanaz a `trades` séma, `mode='paper'` jelöléssel.

---

## 5. Bíró (`judge/`)

### 5.1 Mutatók (`metrics.py`)
Kötésszám, győzelmi arány, profit factor, évesített Sharpe és Sortino (4h gyertyákra: hozamok 4 órás, évesítés √(6·365)), Calmar, max drawdown (mark-equity alapján), átlagos tartási idő, forgás (névérték/tőke/év), nyereséges hónapok aránya, hozam-ferdeség és -csúcsosság (a DSR-hez), rezsimenkénti várható érték (trend×vol kombinációnként), költségérzékenység (1x, 2x, 3x díj mellett újraszámolt PF).

### 5.2 Walk-forward (`walkforward.py`)
Gördülő ablakok: 12 hónap in-sample, 3 hónap out-of-sample, 3 havonta lépve, az egész történelmen a holdout kivételével. A paramétereket **nem** optimalizáljuk ablakonként (a variáns fix paraméterű), az ablakozás a stabilitást méri: OOS-Sharpe mediánja / IS-Sharpe mediánja = OOS/IS arány.

### 5.3 CPCV és PBO (`cpcv.py`, `pbo.py`)
- A holdout nélküli időszak N=8 egyenlő blokkra osztva, k=2 blokk teszt, 28 kombináció; purging 7 nap, embargó 3 nap a blokkhatárokon.
- PBO Bailey et al. szerint: a tesztelés egy **variáns-családon** fut (az azonos hipotézisből született paraméter-variánsok mátrixán), a rangsor-logit eloszlásából a túlillesztés valószínűsége. Ha egy hipotézisnek csak 1 variánsa van, a PBO a család összes variánsán számolódik.
- Küszöb: PBO < 0,2.

### 5.4 Deflated Sharpe (`dsr.py`)
Bailey–López de Prado képlet: a várt maximális Sharpe N független kísérlet mellett (N = a kísérletnapló összes bejegyzése az adott családban az elmúlt 90 napban, a bukottakkal együtt; a variánsok korrelációja miatt N hatékony értéke a korrelációs mátrix sajátértékeiből becsült „effective number of trials”), a hozamok ferdeségével és csúcsosságával, T megfigyeléssel. Kimenet: valószínűség, hogy a valódi Sharpe > 0. Küszöb: > 0,95.

### 5.5 Kísérletnapló (`ledger.py`, `trials` tábla)
Minden `signals()`-futásról egy sor: `trial_id, strategy_id, family, hypothesis_id, parent_id, params_hash, data_hash, judge_version, created_at, is_metrics_json, wf_metrics_json, cpcv_json, dsr, pbo, gate_result, gate_failures, holdout_used (bool), holdout_metrics_json`. A tábla **csak beszúrható**, nem módosítható (trigger védi).

### 5.6 Kapuk (`gates.py`, `config/judge.yaml`)
```yaml
L1_backtest:
  min_trades: 100
  pf_min_at_2x_cost: 1.3
  max_dd_pct: 25
  oos_is_ratio_min: 0.5
  dsr_min: 0.95
  pbo_max: 0.20
  regimes_positive_min: 2
  param_stability: {perturb_pct: 20, must_stay_positive: true}
L1_holdout:                 # egyszer futtatható variánsonként
  pf_min: 1.1
  burn_rule: {same_family_param_delta_pct: 20, cooldown_days: 30}
L2_paper:
  min_trades: 200
  min_regimes: 2
  pf_min: 1.2
  dd_vs_backtest_max_ratio: 1.5
  demote_if: {pf_below: 1.1, dd_ratio_above: 1.5}
L3_micro:
  min_trades: 100
  pf_min: 1.0
  slippage_vs_model_max_ratio: 1.5
  demote_if: {pf_below: 1.0, dd_ratio_above: 1.5}
population: {size: 50, max: 100, cull_bottom_pct: 20, diversity_corr_max: 0.8}
holdout: {months: 6, rolling: true}
```
A `judge.yaml` fájl tetején `version:` és `changelog:` mező; a `trials` sor a `judge_version`-t tárolja, így egy régi kísérlet nem hasonlítható össze új küszöbbel észrevétlenül.

### 5.7 Diverzitás
A paper-populáció napi hozamainak korrelációs mátrixa. Ha két egyed korrelációja > 0,8, a gyengébb DSR-ű kap büntetést a rangsorban (DSR × 0,9). Ez megakadályozza, hogy a populáció egy családra szűküljön.

---

## 6. Evolúciós hurok (`evolve/`)

### 6.1 Napi futás (`evolab daily`, launchd 02:00)
1. `data.update` – Binance napi pótlás, Hyperliquid gyertyák lezárása, rezsimcímkék frissítése.
2. `judge.evaluate_population` – minden L2+ egyed paper-mutatói; akinél a kötésszám elérte a szintje küszöbét, ítélet (lép / marad / kiesik). Kiesett helyére a várólista legjobb DSR-ű jelöltje lép, **ha jóvá van hagyva** (6.4).
3. `report.daily` – `reports/YYYY-MM-DD.md` + JSON: rangsor, rezsim, nyertesek/vesztesek és okaik, diverzitás, várólista, jóváhagyásra várók, kísérletszám-számláló és az aktuális DSR-küszöb magyarázata.
4. `researcher.run` – Claude-hívás (6.2). Kimenet: `hypotheses/YYYY-MM-DD.yaml`, 2-3 hipotézis.
5. `developer.run` – minden hipotézisre Claude Code indítása headless módban (6.3). Kimenet: új variáns-fájlok + L1 visszateszt + ledger-sorok.
6. `ladder.apply` – ami átment L1-en, várólistára; Telegram-összefoglaló a napról, a jóváhagyásra váró egyedek listájával.

Minden lépés idempotens és újrafuttatható (`evolab daily --step researcher`).

### 6.2 Kutató (`researcher.py`)
- Modell: Claude Opus 5.5 a `anthropic` SDK-n át, `claude-opus-5-5` azonosítóval (a pontos azonosítót a `config/lab.yaml` tartalmazza, hogy ne a kódban legyen).
- Bemenet: a napi riport, az elmúlt 14 nap hipotézisei és sorsuk (átment / bukott, miért), a `families.yaml`, és a kísérletszám-számláló.
- Kimenet séma (pydantic-kal validálva, különben elutasítva):
```yaml
- id: H-2026-10-11-01
  family: trend
  parent_strategy_id: trend-donchian-4h-03   # vagy null, ha új
  mutation_type: filter_add | param | crossover | regime_condition | rewrite
  change: "..."                 # mit változtat, 1-3 mondat
  rationale: "..."              # miért kellene működnie, közgazdasági indoklás, min. 200 karakter
  expected_regimes: [up/high, down/high]
  falsifier: "..."              # mi cáfolná
  param_grid: {lookback: [40, 60, 80]}   # max 6 kombináció hipotézisenként
```
- Szabályok a promptban: naponta legalább 1 nem-paraméter mutáció; tilos a holdoutra vagy a paper-időszak konkrét kötéseire hivatkozni; tilos küszöböt vagy kapu-változtatást javasolni; a „mert a visszateszt jó” indoklás elutasítva.
- A prompt sablonja `src/evolab/evolve/prompts/researcher.md`; változtatása csak havi felülvizsgálatban, emberi jóváhagyással (koncepció 4.3).

### 6.3 Fejlesztő (`developer.py`)
- Claude Code-ot headless módban indítja hipotézisenként (`claude -p` a projekt gyökerében, a hipotézis YAML-jával és a `strategy/base.py` felületével a promptban), egy dedikált git-ágon (`evolve/H-...`).
- A fejlesztő csak a `strategy/families/` alatt hozhat létre fájlt. Egy pre-commit hook és egy CI-teszt elutasít minden más változtatást az ilyen ágon (különösen `judge/`, `config/judge.yaml`, `sim/`).
- Lefuttatja: `evolab backtest --strategy <id> --no-holdout`, majd `evolab judge --strategy <id>`. Ha a kapu átmegy, az ág merge-ölődik `main`-be, és a variáns `L1` státuszt kap.
- Hipotézisenként max. 6 paraméter-kombináció; mind a 6 a ledgerbe kerül.

### 6.4 Jóváhagyás (döntve: L2-be csak emberi OK-val)
- A napi Telegram-üzenet felsorolja az L1-et átment, várólistás egyedeket: id, család, hipotézis 1 mondatban, DSR, PBO, PF 2x díjnál, OOS/IS.
- Válasz: `/approve <id>` vagy `/reject <id> <ok>`. Jóváhagyás nélkül az egyed a várólistán marad, nem lép L2-be. 14 nap után a várólistáról lejár (ledger-sor marad).
- L2→L3 és L3→L4 lépés szintén csak `/approve`-val; L-visszalépés automatikus (a bíró dönt, az ember csak értesül).

### 6.5 Mutációs operátorok (`mutations.py`)
Nem az LLM írja, hanem determinisztikus segédfüggvények, amiket a fejlesztő hívhat: `perturb_params(strategy, pct)`, `add_filter(strategy, filter_fn)`, `crossover(entry_from, exit_from)`, `condition_on_regime(strategy, labels)`. A `rewrite` típus az egyetlen, ahol az LLM szabadon ír kódot a sablon felületén belül.

---

## 7. Allokátor (`evolve/allocator.py`)
1. fázisban: egyenlő kockázati súly minden L3+ egyedre (vol-cél már a `risk.py`-ban). Hetente újraszámol. 3 L3-as egyed felett a rezsimfüggő súlyozás külön hipotézisként kerül a kutató elé, és ugyanazon a kapun megy át, mint egy stratégia (az allokátor kimenete egy „meta-stratégia” a ledgerben).

---

## 8. Riport, dashboard, értesítés

- `report/daily.py`: Markdown + JSON, a 6.1/3. pont szerint. Minden szám a `trials` és `trades` táblákból, nem külön számolva.
- `report/dashboard/`: statikus HTML, a napi futás végén generálva, `reports/index.html`. Táblák: torna-rangsor (egyed, család, szint, kötésszám, PF, DSR, PBO, DD, rezsim-lefedettség), családonkénti összesítés, létra-állapot, hipotézis-találati arány családonként, kísérletszám és DSR-küszöb alakulása. Grafikon: populáció equity-görbéi, diverzitás-hőtérkép. Egyszerű, nem kell keretrendszer; a `dataviz` elvei (egységes paletta, világos/sötét mód).
- `notify/telegram.py`: napi összefoglaló, jóváhagyási parancsok, hibaüzenet, ha a napi futás bármely lépése elbukik. Kill switch: `STOP` fájl a gyökérben leállítja a paper-könyvelést és a fejlesztő lépést (a rögzítő nem áll le).

---

## 9. Tesztek (kötelező, `pytest`)

| Teszt | Mit bizonyít |
|---|---|
| `test_no_lookahead` | egy jövőbeli gyertya módosítása nem változtat múltbeli jelet és rezsimcímkét |
| `test_sim_deterministic` | ugyanaz a bemenet → ugyanaz a trades-hash |
| `test_sim_known_answer` | kézzel kiszámolt 5 kötéses példa PnL-je díjjal és fundinggal egyezik |
| `test_judge_rejects_overfit` | egy szintetikus, véletlenre illesztett variáns (100 random paraméter legjobbika) DSR-je < 0,95 |
| `test_judge_accepts_simple` | egy szintetikus, valódi trendet tartalmazó adaton az EMA-kereszt átmegy |
| `test_ledger_append_only` | UPDATE/DELETE a `trials` táblán hibát dob |
| `test_holdout_isolation` | az L1 visszateszt nem tud a holdout-ablakból adatot olvasni (a store szintjén tiltva) |
| `test_developer_sandbox` | az evolve-ágon `judge/` vagy `config/judge.yaml` módosítása elutasítva |
| `test_paper_equals_backtest` | ugyanarra a 30 napra a paper és a visszateszt equity-je ±5%-on belül |
| `test_researcher_schema` | hiányzó/rövid `rationale` → a hipotézis elutasítva |

---

## 10. Fázisok és elfogadási feltételek

| Fázis | Hét | Mi készül | `make verify-N` kimenete |
|---|---|---|---|
| **0 Váz** | 1 | repó, `pyproject`, config fájlok, `db/schema.sql`, CLI váz, Telegram ping, launchd plist | `evolab --version`, DB létrejön, Telegram-üzenet megérkezik |
| **1 Adat** | 1-2 | Binance bulk letöltő checksum-ellenőrzéssel, 6 coin × 3 idősík 2020-tól, Hyperliquid rögzítő fut, rezsimcímkék | hiányzó gyertyák száma 0, checksum OK, `regime_daily` feltöltve, rögzítő 24 órája fut |
| **2 Szimulátor + 1 stratégia** | 2-3 | sablon, `trend` család első variánsa, portfólió-szimulátor költséggel és fundinggal | `test_sim_*` zöld, egy visszateszt lefut és trades/equity parquetet ír |
| **3 Bíró** | 3-4 | metrikák, walk-forward, CPCV, PBO, DSR, ledger, kapuk, holdout-izoláció | `test_judge_*`, `test_ledger_*`, `test_holdout_*` zöld; egy variáns teljes ítélete < 2 perc |
| **4 Induló populáció** | 4-5 | 40 variáns az 5 családból, mind a ledgerben, L1 ítélettel | riport: hány ment át L1-en családonként |
| **5 Élő paper** | 5-6 | paper_runner 4 óránként, L2 könyvelés, napi riport, dashboard v1 | `test_paper_equals_backtest` zöld 30 nap után (addig: napi egyezés-ellenőrzés) |
| **6 Hurok** | 6-7 | kutató, fejlesztő headless, jóváhagyás Telegramon, napi launchd futás | 7 egymást követő napi futás emberi beavatkozás nélkül; hipotézisek a ledgerben |
| **7 Stabilizálás** | 8 | diverzitás-büntetés, HMM-címkéző variáns, hibakezelés, dokumentáció | `make verify-all` zöld; `docs/STATUS.md` naprakész |

Az L3 mikro-éles végrehajtó (`live/executor.py`, Hyperliquid SDK, API-tárca a fő tárcától elválasztva, max. 50 USD) **nem része az első 8 hétnek**. Külön specifikáció, amikor az első egyed eléri az L2 kapuját.

---

## 11. Claude Code munkarend

- `CLAUDE.md` a gyökérben: a 0. fejezet alapelvei, a védett fájlok listája, a `make verify-N` használata, a döntésnapló (`docs/DONTESEK.md`) vezetése.
- Egy fázis = egy PR. A PR leírása tartalmazza a `make verify-N` kimenetét.
- Minden PR-ban a tesztek zöldek. Ha egy teszt a fázis miatt nem futtatható, kihagyás helyett `xfail` okkal.
- A fejlesztő-LLM (6.3) futásai külön ágakon, a `strategy/families/` alá korlátozva. Ezeket a PR-okat a bíró „review-olja” (a kapu), nem ember.
- A `data/` mappa gitignore-olt; a Mac minin Time Machine vagy rsync menti.

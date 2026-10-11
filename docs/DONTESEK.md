# Döntésnapló

A specifikációban nem rögzített, megvalósítás közben hozott döntések. Új bejegyzés a lista végére.

| Dátum | Fázis | Döntés | Indok |
|---|---|---|---|
| 2026-10-10 | 0 | A `Makefile` a repó gyökerében van (nem `ops/Makefile`). | Így elég a `make verify-0` a gyökérből, nincs `-C ops`. |
| 2026-10-10 | 0 | Telegram-küldés közvetlenül a Bot API-n `httpx`-szel, nem `python-telegram-bot`-tal. | 0. fázishoz csak küldés kell; a parancsfogadás (`/approve`) a 6. fázisban dönti el, kell-e a nagyobb könyvtár. |
| 2026-10-10 | 0 | `hmmlearn` opcionális függőség (`regime` extra). | Csak a 2. fázistól kell; így a 0. fázis telepítése kevesebb natív fordítással jár. |
| 2026-10-10 | 0 | A `ladder_events` tábla is csak beszúrható. | A létra-előzmény ugyanúgy bizonyíték, mint a kísérletnapló. |
| 2026-10-10 | 0 | A launchd feladat LaunchAgent (felhasználói), nem LaunchDaemon. | Nem kell root; a Mac minin a felhasználó be van jelentkezve. Feltétel: automatikus bejelentkezés újraindítás után. |
| 2026-10-10 | 0 | Telepítő szkript (`scripts/setup-mac.sh`) végigvezeti a Telegram beállítást is. | A felhasználó nem programozó; egy parancs legyen a teljes 0. fázis. |
| 2026-10-10 | 0 | A launchd saját stdout/stderr naplója a `~/Library/Logs/evolutiontrader/` mappába kerül, a plistben nincs `WorkingDirectory`. | Az első próbán a launchd 78-as (EX_CONFIG) kóddal leállt, mert a külső kötet `logs/` mappáját nem érte el. A belső lemezen lévő napló mindig írható, így a hiba oka látható; a szkript maga lép be a repóba. |
| 2026-10-10 | 1 | `.gitignore`: a `data/`, `logs/`, `reports/` minták a gyökérhez kötve (`/data/`). | A `data/` minta a `src/evolab/data/` forráskönyvtárat is kizárta a gitből. |
| 2026-10-10 | 1 | CLI: `evolab data update`, `evolab data gaps`, `evolab data check`, `evolab regime`, `evolab recorder [--once]`. | A feladatleírás `evolab data update` formát kért; a többi adatparancs ugyanebbe a csoportba került. |
| 2026-10-10 | 1 | A letöltő a tárhely S3-listájából dönti el, mely havi/napi zipek léteznek; a coin első elérhető hónapjától tölt (`history_start` = 2020-01 alsó korlát). | Nincs 404-próbálgatás; a később listázott coinok (pl. SOL 2020-09) maguktól a saját kezdetüktől indulnak. |
| 2026-10-10 | 1 | Az ellenőrzött zipek a `data/raw/binance/` gyorsítótárban maradnak a Binance-checksummal együtt; a parquet ezekből épül újra. | Idempotencia: újrafuttatáskor csak a hiányzó zip töltődik le; a `verify-1` bármikor újraellenőrzi a teljes gyorsítótár checksumját. |
| 2026-10-10 | 1 | A havi zipekből néha egész napok hiányoznak (főleg `markPriceKlines`, `premiumIndexKlines`, pl. BTC 2021-07-24..27, 2026-06-29). A parquet építése után minden hiányzó gyertyát egyszer a Binance REST API-ból (`fapi/v1/*Klines`) pótolunk; ami ott sincs, valódi hiány. | Az API ugyanazt az adatot adja; a napi zip a havival lefedett hónapra nem töltődik le. |
| 2026-10-10 | 1 | A `fundingRate` csak havi fájlban létezik a data.binance.vision-ön; az aktuális hónap fundingja a REST API-ból (`fapi/v1/fundingRate`) jön. | Nincs `daily/fundingRate` útvonal. |
| 2026-10-10 | 1 | Az OI a `daily/metrics` fájlokból jön (`data/binance/<symbol>/metrics.parquet`, 5 perces), 2021 végétől érhető el; előtte a pozícionáltság csak a fundingból számol. | A spec 2.4 OI-t kér; a Binance archívumban ez a forrás. |
| 2026-10-10 | 1 | Időbélyeg-egység: 10^14 feletti érték mikroszekundum, ezt ms-re osztjuk (`universe.to_ms`). A CSV fejléce opcionális: ha az első cella nem szám, fejlécsorként eldobjuk. | A Binance 2025-től helyenként µs-t ad, a régi CSV-kben nincs fejléc. |
| 2026-10-10 | 1 | Hiánykategóriák: `outage` (lent listázott valódi leállás), `missing_file` (nincs zip a napra/hónapra), `gap` (a zip megvan, a gyertya nincs). A `verify-1` csak akkor zöld, ha az `outage`-on kívül 0 a hiány. Részletes riport: `reports/data_gaps.csv`. | A feladatleírás külön kéri a tőzsdei leállást a hiányzó fájltól. |
| 2026-10-10 | 1 | Rögzítő: percenként JSONL-puffer (`data/hl/buffer/ticks_<nap>.jsonl`), óránként tömörítés napi parquetbe coinonként; a lezárt nap pufferét a sikeres tömörítés törli. A gyertya/funding-szinkron (4 óránként) külön szálon, lassítva (3 mp/kérés) fut, 429/5xx esetén újrapróbál. | Percenkénti parquet-újraírás pazarló; az első (hosszú) gyertya-pótlás ne ejtsen ki perceket. |
| 2026-10-10 | 1 | A rögzítő külön LaunchAgent (`com.evolutiontrader.recorder`, `KeepAlive`, `RunAtLoad`, 30 mp újraindítási késleltetés); a napló a `~/Library/Logs/evolutiontrader/recorder.*.log`. A `ops/install-launchd.sh` alapból mindkét feladatot telepíti, argumentummal csak az egyiket. | Ugyanaz az EX_CONFIG-tanulság, mint a napi futásnál. |
| 2026-10-10 | 1 | Rögzítő elfogadás: az elmúlt 24 óra perceinek ≥95%-ára van pillanatkép, és ≥24 órája fut. | A spec „24 órája fut” feltételét mérhetővé teszi; a hálózati kiesés néhány perce belefér. |
| 2026-10-10 | 1 | Rezsim: `date = D` címke a D napon nyíló (D+1 00:00-kor záró) napi gyertyából, a D napi fundingból és a D nap utolsó OI-jából. Stratégia a D+1 napi gyertyáihoz a D címkét használhatja. Paraméterek: ADX(14) < 20 → flat; vol-percentilis 365 napos ablak, min. 180 nap; funding-z 30 napos, küszöb ±1,5; OI 7 napos változás > 0 kell a „crowded” címkéhez. Az első ~200 nap (EMA200 bemelegedés) kimarad. | A spec 2.4 küszöbei; a nem rögzített paraméterek a `lab.yaml` `regime:` blokkjával felülírhatók. |
| 2026-10-10 | 1 | A parquet-újraépítés csak akkor marad ki, ha nincs új zip, a sor naprakész, ÉS nincs benne hiányzó gyertya vagy üres `mark_close` (a `premium_close` tájékoztató; pl. BTC 2020-12-01 egy órája a forrásban sincs meg). Ha van lyuk, a REST API-pótlás minden futáskor újra megpróbálja. | Az első futáskor a SOL/XRP 2022-02-26..28 és 2022-04-01..02 napjai hiányoztak a havi zipből, és a korai kilépés miatt a pótlás sosem futott le. |
| 2026-10-10 | 1 | Dátum-szövegből (metrics `create_time`) az ms-időbélyeg `dt.as_unit("ms")`-val készül, nem ns-feltételezéssel. | A pandas 3 a szöveges dátumot µs-felbontásban adja; a régi `// 10**6` másodpercet adott (1970-es dátumok az OI-ban). |
| 2026-10-10 | 1 | A 0 kötéses (lapos, volume = 0) gyertya is hiánynak számít, hacsak nem esik egy lent listázott leállásba; a `verify-1` kiírja a darabszámukat („üres”). A gyertya az archívumi (checksummal ellenőrzött) értékével marad a parquetben. | A Binance a kereskedési szünetet nem hiányzó sorral, hanem 0 forgalmú, lapos gyertyával jelzi; az ilyen óra a szimulátorban hamis teljesülést adhatna, ezért láthatóvá kell tenni. |
| 2026-10-10 | 1 | Funding-rés ellenőrzése intervallumváltáskor a régi és az új intervallum közül a hosszabbal számol. | SOL 2022-11-10-én 4 óráról 1 órás fundingra váltott; ez nem hiány. |

## Ismert Binance-leállások

Valódi tőzsdei kiesések (nem adathiba, nem hiányzó fájl). UTC, a vég kizárólagos; `*` = minden coin. A `src/evolab/data/gaps.py` ezt a táblát olvassa: új sor csak ellenőrzés után, indoklással.
Keresés módja (2026-10-10): a 6 coin 1h/4h/1d sorában 2020-01-01-től a REST-pótlás után 0 hiányzó gyertya maradt; 0 kötéses gyertya egyetlen órában volt, mind a 6 coinra egyszerre.

| Kezdet (UTC) | Vég (UTC) | Coinok | Megjegyzés |
|---|---|---|---|
| 2024-10-28 20:00 | 2024-10-28 21:00 | * | Az archívum havi zipje mind a 6 coinra 0 forgalmú, lapos gyertyát ad (O=H=L=C az előző zárás). A REST API ugyanerre az órára (és a 21:00-s gyertyára) eltérő, forgalmas értéket ad; a checksummal ellenőrzött archívum marad, az óra kiesésként kezelendő. Az ok nincs nyilvánosan dokumentálva. |

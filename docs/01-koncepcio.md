# EvolutionTrader – koncepció és kutatási összefoglaló

*Állapot: 3. változat, 2026-10-10. Minden nyitott kérdés lezárva (10. fejezet). A kód nulláról készül, régi repóra nem építünk. Ez a dokumentum a laboratórium „miért és mit” része. A „hogyan” (technikai specifikáció Claude Code-nak) a következő dokumentum.*

---

## 0. Egy oldalban: mit javaslok

**Piac:** kripto perpetual (örökös határidős) kontraktusok, USD-ben elszámolva, a 6-8 legnagyobb forgalmú coinon (BTC, ETH, SOL, BNB, XRP, DOGE, később bővíthető). Nem spot, nem grid. Indoklás a 2. fejezetben.

**Idősík:** 4 órás és napi gyertyák. Semmi 5 perc alatti. Itt nincs sebességverseny, és a jelek statisztikailag is tartósabbak.

**Adat és tőzsde (döntve):** a visszateszt adata a Binance nyilvános adattárából jön (ingyenes, perpetual 2019-től, spot 2017-től). Az élő paper és a későbbi mikro-éles a Hyperliquidon fut (on-chain, nincs KYC, nyílt API kulcs nélkül, Python SDK). Az első naptól saját rögzítő gyűjti a Hyperliquid élő adatát, mert annak történelme csak 2023-tól van.

**Stratégiacsaládok induláskor (5 család, ~25 variáns):**
1. Trendkövetés / idősoros momentum (a legerősebb akadémiai bizonyíték kriptóban)
2. Volatilitás-kitörés szűkülés után
3. Relatív erő párok (ETH/BTC, SOL/ETH) átlaghoz visszatéréssel
4. Funding-rate és open-interest alapú pozícionáltsági jelek (kontrariánus + szűrő)
5. Sáv-visszatérés oldalazó rezsimben (Bollinger-alapú, csak akkor aktív, ha a rezsimcímke „oldalazó”): az „oldalazó specialista”, alacsony priorral

**Hogyan fejlődik (döntve: napi ciklus):** a kutató–fejlesztő–bíró hurok **naponta** fut a történelmi adaton (hipotézis → variáns → visszateszt → kapu). Ez a gyors rész, mert a múlt nem vár. Az élő paper-populáció kiértékelése folyamatos, de az elő- és visszaléptetés **kötésszámhoz** kötött, nem naptárhoz, mert 4 órás gyertyákon egy hét alatt nem gyűlik össze elég kötés egy döntéshez. A populáció fix méretű: csak akkor jön be új egyed, ha egy gyenge kiesik. Minden kísérlet naplózva, a kipróbált variánsok száma a bíró egyik bemenete (deflated Sharpe). Napi ciklus mellett ez a szám gyorsan nő, ezért a DSR-küszöb a valódi fék, nem a számítási kapacitás.

**Védelem túlillesztés ellen (3+1 réteg):** érinthetetlen holdout szakasz (döntve: 6 hónap, plusz az élő paper-idő mint második, folyamatosan növekvő out-of-sample); walk-forward és kombinatorikus (CPCV) validáció; többszörös tesztelés korrekciója (deflated Sharpe, PBO); plusz a „miért működik” kötelező indoklás.

**Előléptetés:** visszateszt → élő paper (min. 200 kötés, 2 rezsim) → mikro-éles (~50 USD) → éles. Minden kapu számszerű, visszalépéssel.

**Reális várakozás:** 2-3 hónap, mire az első stratégia a mikro-éles szintre ér. A rendszer első 8 hete alatt a fő termék nem a hozam, hanem a mérőműszer: egy megbízható bíró és egy tiszta adatfolyam. Ha ez a kettő rossz, minden utána jövő döntés rossz.

---

## 1. Mit mond a kutatás (2024-2026 állás)

Nyitott szemmel néztem körül: van-e már bevált gyakorlat arra, amit építeni akarunk. Három területen találtam használhatót.

### 1.1 Az „LLM mint mutációs operátor” irány már létezik és működik

2025-2026-ban több tanulmány jelent meg pontosan erről: egy nyelvi modell nem maga kereskedik, hanem **stratégiakódot módosít egy evolúciós keretben**, és a kiértékelés különálló, determinisztikus kód.

- **AlgoEvolve** (2026): az LLM „szemantikus mutációs operátor”, futtatható Python stratégiákat alakít át, és egy külső meta-evolúciós hurok magát a mutálás módját is finomítja. A szerzők rezsim-adaptív logika megjelenéséről számolnak be.
- **QuantaAlpha** (2026) és **CogAlpha** (2025/26): minden kutatási „pályát” egyedként kezelnek, mutáció és keresztezés van, és külön kapuk (gating) szűrik a zajt és a nem-stacionaritást.
- **AlphaPROBE** (2026): visszakeresés + irányított evolúció; a klasszikus genetikus programozás (gplearn) a baseline, amit az LLM-es változat ver.
- Egy 2026-os áttekintő tanulmány (*Agentic Quantitative Trading: A Survey*) rendszerezi ezt a területet.

**Tanulság nekünk:** az alapötletünk nem egyedi, hanem egy formálódó bevett gyakorlat. Amit ezek a rendszerek megerősítenek:
- az LLM **kódot** változtat, nem jeleket ad kereskedés közben;
- a fitnesz/kiértékelés **nem az LLM dolga**;
- a populáció és a pályanapló kell, nem egy stratégia;
- a meta-szint (hogyan mutálunk, milyen promptot kap a kutató) maga is fejleszthető.

Amit ezek a tanulmányok **nem** oldanak meg jól, és nekünk kell: a legtöbb kínai részvénypiaci faktor-benchmarkon (CSI300) mér, nem kriptón, és a túlillesztés-védelem gyakran csak egy hold-out. Mi ezt szigorúbbra vesszük.

### 1.2 A túlillesztés elleni eszköztár kiforrott, csak alkalmazni kell

Bailey, Borwein, López de Prado és Zhu munkái (2014-2018) a mérce, azóta nincs jobb:

- **Minimum Backtest Length:** példájuk szerint 5 év napi adaton már ~45 variáns kipróbálása után a legjobb várhatóan 1,0 feletti Sharpe-ot mutat **puszta véletlenből**. Ez pontosan a mi kockázatunk: heti 20-30 variáns.
- **Deflated Sharpe Ratio (DSR):** a mért Sharpe-ot lehúzza a kipróbált variánsok száma és a hozamok nem-normalitása (ferdeség, csúcsosság) szerint. **Ehhez minden kísérletet naplózni kell, a bukottakat is.** Ha csak a nyerteseket írjuk fel, a DSR hazudik.
- **Probability of Backtest Overfitting (PBO)** és **CPCV** (kombinatorikus, tisztított keresztvalidáció): nem egy, hanem sok in-sample/out-of-sample útvonalat generál, és azt nézi, a rangsor stabil-e. Egy forrás szerint a DSR a nagyságot, a PBO a rangsor-stabilitást méri, és a kettő együtt lényegesen erősebb, mint bármelyik külön.
- **Purging és embargó:** ha a címkék átfednek időben (egy 4 órás jel napokig tartó pozíciót nyit), a tanító és a teszt szakasz közé időrést kell tenni, különben szivárog az információ.

**Tanulság nekünk:** a bíró a fenti négy mutatót számolja, nem csak a profit factort. És a kísérletnapló (trial ledger) a rendszer egyik központi adattáblája, nem melléktermék.

### 1.3 Mely kripto-anomáliákra van tényleges bizonyíték

Itt a kép vegyesebb, mint a marketing sugallja.

| Jelenség | Bizonyíték erőssége | Megjegyzés |
|---|---|---|
| Idősoros momentum / trendkövetés nagy coinokon | **Erős.** Liu–Tsyvinski (NBER 2018, Journal of Finance 2022): erős idősoros momentum; a hatás a nagy kapitalizációjú coinokon erősebb. Rozario et al. (2020): egy évtized walk-forward bizonyítéka, árupiaci jellegű viselkedés. | Han–Kang–Ryu: költségek után sok momentum-portfólió eltűnik, az idősoros marad, a keresztmetszeti gyengül. Rövid lookback jobb Sharpe-ot ad, de a sűrű újrasúlyozás költsége ezt viszi (Monash). |
| Funding rate mint kontrariánus jel | **Gyenge/vitatott.** A BitMEX saját elemzése szerint a funding önmagában nincs szignifikáns előrejelző erővel. Egy blogteszt 0,84 Sharpe-ot mutat long-only, költség nélkül. | A szélsőséges funding-epizódok száma 2016 óta ~90%-kal csökkent. **Szűrőként** (pozícióméret, irány-tiltás) valószínűbb a hasznossága, mint önálló belépőjelként. |
| Rezsimdetektálás rejtett Markov-modellel | **Közepes.** 4 állapotú HMM Bitcoinon bull/bear/calm rezsimeket különít el, és egy US részvény tanulmányban rezsim-alapú modellváltás out-of-sample jobb, mint bármelyik egyedi modell. | Ez a mi allokátor-rétegünk közvetlen precedense. |
| Volatilitás-kitörés | **Nincs független bizonyíték** 4h/napi szinten költségek után. A talált tesztek rács-keresésesek (= többszörös tesztelés). | Marad a populációban, de alacsony prior-ral; a bíró dönt. |
| Átlaghoz visszatérés párokon (ETH/BTC) | **Nem találtam** peer-reviewed kointegrációs bizonyítékot ETH/BTC-re. | Közgazdasági logika van (ugyanaz a kockázati étvágy mozgatja), bizonyíték nincs. Alacsony prior. |

**Tanulság nekünk:** a populáció induló súlya ne legyen egyenletes. A trendkövető család kapja a legtöbb variánst (10-12), a többi 3-5-öt. A funding-jel elsősorban szűrő és rezsim-címke, nem önálló stratégia.

---

## 2. Piacválasztás: mire és hol

### 2.1 Spot, grid vagy perpetual?

| | Spot | Grid bot | Perpetual |
|---|---|---|---|
| Short lehetséges | nem | nem | **igen** |
| Funding/OI adat mint jel | nincs | nincs | **van** |
| Trendkövetés mindkét irányba | fél | nem | **igen** |
| Veszteség oldalvolat piacon | tartás | **nyer**, de trendben kiürül | stratégiafüggő |
| Tőkeigény kis tétnél | magas | magas | alacsony (de tőkeáttét = kockázat) |
| Paper-szimuláció pontossága | könnyű | könnyű | **nehezebb** (funding, likvidáció, mark vs. last) |

**Javaslat: perpetual, 1-2x tőkeáttéttel maximum.** Három ok:
1. A legerősebb bizonyítékkal rendelkező család (trendkövetés) csak akkor teljes, ha short is lehet. Bear piacon spot trendkövetés csak készpénzben ül.
2. A funding és open interest egyedi kripto-adat, ami csak itt létezik, és rezsimjelnek jó.
3. A kis tőke (50 USD mikro-éles) csak itt értelmezhető: spotban 50 USD-ből a díjak elviszik a hozamot.

A grid bot nem stratégia, hanem egy fix viselkedés (oldalazó piacon pénzt szed, trendben készletet halmoz). **Egy grid-variáns bekerülhet a populációba** mint „oldalazó rezsim specialista”, de az egész rendszer alapjaként rossz, mert nem tud fejlődni.

Fontos ár: a perpetual szimulátornak modelleznie kell a funding-fizetést (8 óránként), a mark árat, a likvidációs küszöböt és a díjakat (taker ~0,035-0,05%, maker kevesebb). Ha ezt elhagyjuk, a paper-eredmény hazudik.

### 2.2 Melyik tőzsde (adat és később kivitelezés)

- **Adatforrás:** Binance (legmélyebb likviditás, 2017-től ingyenes nyilvános adattár: gyertyák minden felbontásban, futures mark/index/premium index). Hyperliquid nyílt Info API: funding, OI, gyertyák, kulcs nélkül.
- **Paper-végrehajtás:** saját szimulátor az élő Binance/Hyperliquid árfolyamon, **nem** tőzsdei testnet. A testnet likviditása nem valós, és a testnet-adat nem reprodukálható.
- **Mikro-éles és éles (döntve): Hyperliquid.** On-chain, tárcával lép be az ember, nincs KYC, a nyilvános API kulcs nélkül megy, van Python SDK és testnet. A Binance marad adatforrásnak (ott van a hosszú történelem), de nem végrehajtó.

**Miért nem a Hyperliquid adata a visszateszthez?** Mert rövid: a Hyperliquid 2023-ban indult, a Binance perpetual 2019-ben. A 2020-as összeomlás, a 2021-es bika, a 2022-es medve csak a Binance adatban van benne, és pont ezek a rezsimek kellenek a „2 rezsimben pozitív” kapuhoz. A nagy coinok ára a két tőzsdén század-százalékon belül együtt mozog, a funding viszont eltérhet, ezért a funding-alapú jeleket az élő paper szakaszban a Hyperliquid saját funding-adatán kell újra igazolni. A rögzítő ezért az első naptól gyűjti a Hyperliquid funding/OI/ár adatát, és egy év múlva már saját, végrehajtó-tőzsdei adatunk is lesz.

### 2.3 Coinok és idősík

- **Induló univerzum:** BTC, ETH, SOL, BNB, XRP, DOGE. Kritérium: top-10 napi perpetual forgalom, min. 3 év adat. Évente felülvizsgálat kóddal, nem kézzel.
- **Idősík:** 4h a jelképzésre, 1D a rezsimcímkére. Ok: itt a díj/hozam arány elviselhető, a jelek túlélik a költséget, és nincs ellenfél, aki milliszekundumban gyorsabb.
- CHoCH+FVG bot: nem található egyik repódban sem (lásd 10. fejezet), ezért nem része az induló populációnak.

---

## 3. Mutatók: mit mér a bíró

A bíró kód. Minden stratégiavariánsról ugyanazt a mutatókészletet számolja, ugyanazon az adaton, ugyanazzal a költségmodellel.

### 3.1 Kötelező alapmutatók (minden szinten)
| Mutató | Mit mond | Miért kell |
|---|---|---|
| Kötésszám | hány lezárt kötés | 30 alatt semmi nem szignifikáns |
| Profit factor | bruttó nyereség / bruttó veszteség | egyszerű, robusztus |
| Max drawdown | legnagyobb visszaesés | ez öl meg a valóságban |
| Sharpe (évesített) | hozam/szórás | iparági közös nyelv |
| Sortino, Calmar | lefelé szórás, hozam/DD | a Sharpe egyedül félrevezet |
| Átlagos tartási idő, forgás | mennyit kereskedik | költségérzékenység |
| Költségérzékenység | eredmény 1x, 2x, 3x díj mellett | ami 2x díjnál eltűnik, nem valódi |

### 3.2 Túlillesztés-mutatók (ezek döntenek az előléptetésről)
| Mutató | Küszöb (induló javaslat) |
|---|---|
| **Deflated Sharpe (DSR)** a heti kísérletszámmal | > 0,95 valószínűség, hogy a valódi Sharpe > 0 |
| **PBO** (CPCV, min. 16 út) | < 0,2 |
| **OOS/IS arány** (walk-forward) | out-of-sample Sharpe ≥ 50%-a az in-sample-nek |
| **Holdout eredmény** | csak az előléptetési kapunál fut, egyszer, és naplózva |
| **Rezsim-lefedettség** | pozitív várható érték legalább 2 különböző rezsimben |
| **Paraméter-stabilitás** | ±20% paraméterváltásra az eredmény ne forduljon negatívba |

### 3.3 Rezsimcímkék (minden stratégia bemenete, kódból)
Napi szinten, három tengelyen: **trend** (pl. 50/200 napi átlag + ADX), **volatilitás** (realizált vol percentilis), **pozícionáltság** (funding percentilis, OI-változás). Induláskor szabályalapú; később HMM (4 állapot) mint variáns. Az LLM címkézés csak **javaslat** a kutatói riportban, a bíró a kódból számolt címkét használja.

---

## 4. Hogyan lesz fejlődő: az evolúciós hurok

### 4.1 Két óra, két sebesség

A rendszerben két óra jár. A **kutató óra** gyors, mert a történelmi adaton bármennyi kísérlet futhat. A **bizonyító óra** lassú, mert az élő piacon a kötések csak annyi sebességgel jönnek, amennyivel jönnek. A kettőt nem szabad összekeverni: a gyors óra termeli a jelölteket, a lassú óra dönt róluk.

**Napi ciklus (kutató óra, minden éjjel):**
1. **Bíró** frissíti a mutatókat a paper-naplón és a kísérletnaplón, és generál egy napi riportot: ki nyert és vesztett tegnap, milyen rezsimben, hol tart a populáció diverzitása.
2. **Kutató (Claude)** a riportból 2-3 **hipotézist** ír. Kötelező mezők: mi a változtatás, **miért kellene működnie közgazdaságilag**, mely rezsimben várható javulás, mi cáfolná. Ha a „miért” hiányzik, a hipotézis nem fut.
3. **Fejlesztő (Claude Code)** a hipotézisekből variánsokat ír a stratégiasablonból, lefuttatja a bíró visszatesztjét (holdout **nélkül**). Minden futás a kísérletnaplóba kerül, akkor is, ha bukik.
4. Ami átmegy az L1 kapun, **várólistára** kerül.

**Kötésszám-vezérelt ciklus (bizonyító óra, a bíró minden nap ellenőrzi, de csak akkor cselekszik, ha a feltétel teljesül):**
5. Egy paper-egyed akkor kap ítéletet, amikor elérte a szintjéhez tartozó kötésszámot (L2: 200). Akkor vagy lép, vagy kiesik. Nincs „pénteken döntünk” szabály.
6. Ha egy egyed kiesik, a várólistáról a legmagasabb DSR-ű jelölt lép a helyére. Fix populációméret: **induló 50 egyed**, bővítés 100-ig, amint a napi kiértékelés elfér a gépen.
7. **Allokátor** hetente számol újra (ennek nem kell gyorsabb, a súlyok lassú jelek).

**Hogyan lesz így gyorsabb a fejlődés?** Három karral, amik mind a kutató órát gyorsítják, és egyik sem rontja a bizonyítékot:
- **Napi hipotézis helyett heti:** 7x több jelölt ugyanannyi idő alatt.
- **Nagyobb populáció:** 50 egyed 4 órás gyertyán, 6 coinon kb. 10-30 kötést termel naponta összesen, tehát egy egyed hamarabb ér el 200-at, ha több coinon fut. Ezért minden stratégia **több coinon egyszerre** fut, egy portfólióként mérve.
- **1 órás variánsok a trendkövető családban:** több kötés, de magasabb költség. A bíró 2x díj mellett is pozitív PF-et követel, ez automatikusan kiszűri, ha az 1 órás nem bírja a költséget.

**Mi az ára a gyorsabb ciklusnak?** A kísérletszám. Napi 10-20 variánssal egy hónap alatt 300-600 kísérlet gyűlik. A deflated Sharpe ezt beárazza: ennyi próbálkozás után egy variánsnak már 1,5-2,0 feletti nyers Sharpe kell, hogy a DSR átengedje. **Ez helyes így.** A gyors ciklus nem a mércét lazítja, hanem több jelöltet állít a változatlan mérce elé.

### 4.2 Honnan jön az új variáns (mutációs operátorok)
- **Paraméter-mutáció:** lookback, küszöb ±20-50%.
- **Szűrő hozzáadás/elvétel:** volumen, volatilitás, funding, napszak/hétvége.
- **Keresztezés:** egy család belépője + másik család kilépője.
- **Rezsim-feltételezés:** ugyanaz a szabály, csak bizonyos rezsimcímke alatt aktív.
- **Családon belüli újraírás:** az LLM átfogalmazza a szabályt (AlgoEvolve-stílus), de a sablon API-ján belül.

A kutató minden nap köteles legalább egy **nem-paraméter** mutációt javasolni, különben a populáció összeszűkül egy család körül (ezt a bíró méri: ha a top 10 páronkénti korrelációja > 0,8, diverzitás-büntetés).

### 4.3 Meta-szint (a rendszer önmagát is javítja, de lassan)
Havonta egyszer a kutató a **saját hipotéziseinek találati arányát** nézi: a 4 hét alatt javasolt hipotézisek hány %-a ment át a kapun, családonként. Ez a kutatói prompt egyetlen megengedett bemenete a változtatáshoz. Az AlgoEvolve ezt hívja meta-evolúciónak. Nálunk ez emberi jóváhagyással történik, nem automatikusan.

### 4.4 Mi az, ami **soha** nem változik automatikusan
- A holdout időszak határai.
- A bíró képletei és küszöbei.
- A költségmodell.
- Az előléptetési létra kapui.
Ezek verziózottak, és változtatás csak explicit döntéssel, dátummal, indoklással.

---

## 5. Előléptetési létra (számszerű kapuk)

| Szint | Belépés feltétele | Kilépés (visszalépés) feltétele |
|---|---|---|
| **L0 Hipotézis** | van közgazdasági indoklás | – |
| **L1 Visszateszt** | DSR > 0,95; PBO < 0,2; OOS/IS ≥ 0,5; PF > 1,3 2x díjnál; max DD < 25%; ≥ 100 kötés | – |
| **L2 Élő paper** | L1 + holdout-on PF > 1,1 (egyszer, naplózva) | 200 kötés után PF < 1,1, vagy DD > 1,5× visszatesztelt DD, vagy 2 rezsimben nincs pozitív EV |
| **L3 Mikro-éles (~50 USD)** | L2 ≥ 200 kötés, ≥ 2 rezsim, paper PF ≥ 1,2, realizált slippage ≤ modellezett ×1,5 | 100 kötés után élő PF < 1,0 vagy DD > paper DD ×1,5 |
| **L4 Éles** | L3 ≥ 100 kötés, élő/paper eltérés < 30%; allokátor által elfogadott | bármikor, ha az L3 kilépési feltétel teljesül |

A holdout (döntve): az utolsó **6 hónap** adat, amit az L1 visszateszt soha nem lát. A holdout-futás eredménye naplózva; egy variáns **egyszer** futhat rajta. Ha megbukik, az ugyanabból a családból származó, 20%-nál kisebb paraméterváltozású variáns **30 napig** nem futhat rajta (holdout-égetés elleni szabály; napi ciklusnál ez szigorúbb kell legyen, mint hetinél).

A 6 hónap rövidebb, mint a szokásos 12, ezért két kiegészítés van:
- A holdout **nem rögzített naptári szakasz, hanem gördülő**: a mai naptól visszafelé 6 hónap. Ami ma holdout, az fél év múlva fejlesztési adat, és a helyére az élő paper-időszak lép, amit a stratégia valóban nem látott.
- Az L2 paper-szakasz a második holdout. Ott a rendszer nem tud csalni, mert a jövő nem tölthető le.

---

## 6. Allokátor (a meta-réteg)

Amíg nincs 3 L3-as stratégia, az allokátor egyszerű: **egyenlő kockázat** (volatilitás-cél, pl. minden stratégia napi 1% kockázatra skálázva). Ettől a ponttól kezdve kísérletezhető:
- rezsimfüggő súlyok (HMM-állapotonként külön súlyvektor, walk-forward tanulva),
- inverz-korreláció súlyozás,
- „bizalom” súly: élő/paper eltérés alapján.

Az allokátor maga is egy stratégia a bíró szemében: ugyanazok a kapuk vonatkoznak rá. Ez az, amit a professzionális alapok csinálnak, és ami kis tőkével is tanulható papíron.

---

## 7. Architektúra vázlat (nem technikai részletezés)

```
[Adatgyűjtő]  Binance Vision bulk + Hyperliquid Info API + saját élő rögzítő
      │           (parquet fájlok, DuckDB lekérdezés)
      ▼
[Rezsimcímkéző] kód: trend / vol / pozícionáltság → napi címkék
      │
      ▼
[Stratégiasablon] egy Python osztály: jel(), méret(), kilépés(); csak ezt írja az LLM
      │
      ▼
[Szimulátor]  visszateszt + élő paper ugyanazzal a kóddal (funding, mark ár, díj, slippage)
      │
      ▼
[Bíró]        mutatók, DSR, PBO, CPCV, walk-forward, holdout-kapu, kísérletnapló
      │
      ├──► [Heti riport] → [Kutató: Claude] → hipotézisek → [Fejlesztő: Claude Code]
      │
      ▼
[Allokátor]   súlyok rezsim szerint
      │
      ▼
[Végrehajtó]  L3/L4: tőzsdei adapter (Hyperliquid SDK / CCXT); L0-L2: nincs
      │
      ▼
[Dashboard]   torna-tábla, családok, rezsimek, létra állapota
```

**Eszközjavaslat:** Python; saját, vektorizált szimulátor (a perpetual-specifikus költségmodell miatt; a vectorbt jó alap, de a funding-logika hiányzik belőle); DuckDB + parquet az adatra; CCXT vagy Hyperliquid SDK a későbbi végrehajtásra; a NautilusTrader erős, de a tanulási költsége nagy, és csak L3-tól lenne szükség rá. Egy ember + Claude Code mérete mellett a saját, kicsi, érthető szimulátor jobb, mint egy nagy keretrendszer.

**Kód (döntve): nulláról, új repóban (ez).** A `galgoczy/bot` repó egy 2026 májusi, félbemaradt visszateszt-kísérlet; nem építünk rá. Két dolgot érdemes belőle csak *számként* átvenni, nem kódként: a költségmodell induló értékeit (maker 0,02%, taker 0,04%, slippage 0,02%, funding 8 óránként) és azt a tanulságot, hogy egy coin, 1 órás gyertya, 2 év adat kevés volt egy döntéshez. Az új rendszer ezért indul 6 coinnal, 4 órás gyertyával és a lehető leghosszabb Binance-történelemmel.

---

## 8. Mi az, amit ez a rendszer **nem** old meg

- **Nem ad gyorsan pénzt.** Az első 8 hét kimenete egy bíró, egy adatfolyam és egy 30 fős populáció paper-naplója. Hozam nincs.
- **Nem véd a rezsimváltástól, amit még nem látott.** 2021-es és 2022-es adat van, de a következő válság más lesz. Ezért a visszalépési szabályok.
- **Nem helyettesíti a te döntésedet** a bíró képleteiről és a tőzsdeválasztásról.
- **A bizonyíték kriptóban vékonyabb, mint részvényben.** A trendkövetés kivételével minden családot „valószínűleg zaj” prior-ral kezeljünk, amíg a bíró mást nem mond.

---

## 9. Első 8 hét ütemterv

| Hét | Mi készül | Mi a siker jele |
|---|---|---|
| 1-2 | Adatgyűjtő + rezsimcímkéző + 1 trendkövető stratégia + szimulátor | egy visszateszt reprodukálhatóan lefut, költséggel, funding-gal |
| 3-4 | Bíró (összes mutató, DSR, PBO, walk-forward), kísérletnapló, holdout elkülönítve | a bíró egy tudottan túlillesztett variánst elutasít, egy egyszerűt átenged |
| 5 | Élő paper futtatás 10 variánssal, napi riport | a paper-napló és a visszateszt ugyanarra az időszakra egyezik (±5%) |
| 6 | Kutató és fejlesztő hurok az első heti riporton, 5 hipotézis | a hipotézisek naplózva, 1-2 bekerül L2-be |
| 7-8 | Populáció 30-ra bővítve, mind az 5 család, CHoCH+FVG beillesztve, dashboard v1 | heti torna lefut emberi kéz nélkül |

---

## 10. Döntések (2026-10-10) és ami még nyitott

| Kérdés | Döntés | Következmény |
|---|---|---|
| Ciklus gyakorisága | **Napi** kutató-ciklus; elő/visszaléptetés kötésszám alapján, nem naptár alapján | több jelölt, változatlan mérce; a DSR-küszöb emelkedik a kísérletszámmal |
| Tőzsde | **Binance = adat** (hosszú történelem), **Hyperliquid = élő paper és végrehajtás** (nincs KYC, nyílt API) | funding-jeleket a Hyperliquid saját adatán újra kell igazolni L2-ben; rögzítő az első naptól |
| Holdout | **6 hónap, gördülő** | szigorúbb holdout-égetési szabály (30 nap tiltás családon belül); az élő paper a második holdout |
| Populáció | **50 indulásra, 100-ig bővíthető**; minden stratégia több coinon fut egy portfólióként | gyorsabban gyűlik a 200 kötés; a gép napi kiértékelési ideje a korlát, nem a tárhely |
| Kutató automatizmusa | **L1-ig jóváhagyás nélkül fut, L2-be (élő paper) csak a te jóváhagyásoddal lép egyed** | a napi riport végén egy rövid „jóváhagyásra vár” lista; Telegram-értesítés, mint a JEVsniper botnál |
| Gép | **Saját Mac mini, 0-24** | nincs felhőköltség; a napi hurok ütemezése launchd-vel vagy pm2-vel (a JEVsniper már pm2-vel fut ugyanezen a gépen); a Claude-hívások a kutató lépéshez API-kulccsal mennek, a Claude Code fejlesztő lépés helyben fut |
| CHoCH+FVG bot | **Nem található.** Átnéztem a GitHub-fiókod repóit (JEVsniper, bot, cointidy és a többi): egyikben sincs CHoCH vagy FVG kód. Valószínűleg egy korábbi beszélgetésben tervezett, de meg nem írt bot. | kimarad az induló populációból; ha később előkerül a leírása, a kutató egy hipotézisként beviszi, ugyanazon a kapun át, mint bármi mást |
| Kiindulási kód | **Új, nulláról, ebben a repóban.** A `galgoczy/bot` egy régi, félbemaradt kísérlet, nem építünk rá. | csak a költségmodell számai és a „kevés adat volt” tanulság jön át (7. fejezet) |

**Nincs több nyitott kérdés.** A következő lépés a technikai specifikáció Claude Code-nak.

---

## 11. Források

Túlillesztés-védelem:
- [Purged cross-validation (Wikipedia)](https://en.wikipedia.org/wiki/Purged_cross-validation)
- [Probability of Backtest Overfitting (LuxAlgo)](https://www.luxalgo.com/library/concept/probability-of-backtest-overfitting.md)
- [Backtest overfitting and the Deflated Sharpe Ratio (tradinginterview)](https://www.tradinginterview.com/courses/machine-learning/lessons/backtest-overfitting-and-the-deflated-sharpe-ratio/)
- [Bailey, Borwein, López de Prado, Zhu: Pseudo-mathematics and financial charlatanism / MinBTL](https://carmamaths.org/jon/backtest.pdf)
- [Bailey & López de Prado: The Deflated Sharpe Ratio (SSRN)](https://papers.ssrn.com/abstract=2606462)
- [Bailey et al.: The Probability of Backtest Overfitting](https://carmamaths.org/jon/BODT.pdf)
- [Backtesting & Research Methodology (tradingstrategy.ai)](https://tradingstrategy.ai/docs/learn/backtesting.html)

LLM-vezérelt evolúciós stratégiafejlesztés:
- [AlgoEvolve: LLM-driven Meta-evolution of Algorithmic Trading Programs (arXiv 2606.26173)](https://arxiv.org/pdf/2606.26173)
- [QuantaAlpha: An Evolutionary Framework for LLM-Driven Alpha Mining (arXiv 2602.07085)](https://arxiv.org/abs/2602.07085)
- [Cognitive Alpha Mining via LLM-Driven Code-Based Evolution (arXiv 2511.18850)](https://arxiv.org/pdf/2511.18850)
- [AlphaPROBE (arXiv 2602.11917)](https://arxiv.org/pdf/2602.11917)
- [Agentic Quantitative Trading: A Survey (arXiv 2608.31041)](https://arxiv.org/pdf/2608.31041)

Kripto-anomáliák bizonyítéka:
- [Liu & Tsyvinski: Risks and Returns of Cryptocurrency (NBER w24877)](https://www.nber.org/system/files/working_papers/w24877/w24877.pdf)
- [Liu, Tsyvinski & Wu: Common Risk Factors in Cryptocurrency (NBER w25882)](https://www.nber.org/papers/w25882.pdf)
- [Rozario et al.: A Decade of Evidence of Trend Following Investing in Cryptocurrencies (arXiv 2009.12155)](https://arxiv.org/pdf/2009.12155)
- [Time Series and Cross Sectional Momentum in the Cryptocurrency Market (AUT)](https://acfr.aut.ac.nz/__data/assets/pdf_file/0009/918729/Time_Series_and_Cross_Sectional_Momentum_in_the_Cryptocurrency_Market_with_IA.pdf)
- [Monash: Trend-following strategies for crypto investors](https://www.monash.edu/business/monash-centre-for-financial-studies/our-research/all-projects/investment-strategy/trend-following-strategies-for-crypto-investors)
- [BitMEX: XBTUSD Funding Mean Reversion Strategy](https://www.bitmex.com/blog/xbtusd-funding-mean-reversion-strategy)
- [The Two-Tiered Structure of Cryptocurrency Funding Rate Markets (MDPI)](https://www.mdpi.com/2227-7390/14/2/346)
- [Exploring the Predictability of Cryptocurrencies via Bayesian Hidden Markov Models (arXiv 2011.03741)](https://arxiv.org/pdf/2011.03741.pdf)
- [HMM/HSMM Bitcoin vs S&P 500 (University of Malta)](https://www.um.edu.mt/library/oar/bitstream/123456789/98539/1/Analysis%20and%20comparison%20of%20Bitcoin%20and%20S%20and%20P%20500%20market%20features%20using%20HMMs%20and%20HSMMs.pdf)
- [Regime-switching factor allocation (MDPI JRFM)](https://www.mdpi.com/1911-8074/13/12/311/htm)

Adat és eszközök:
- [Binance Public Data (hivatalos repo)](https://github.com/binance/binance-public-data/)
- [binance-bulk-downloader](https://github.com/aoki-h-jp/binance-bulk-downloader)
- [Hyperliquid API docs](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api.md)
- [hyperliquid-python-sdk](https://pypi.org/project/hyperliquid-python-sdk/)
- [Hyperliquid funding rate history guide (OneKey)](https://onekey.so/blog/ecosystem/hyperliquid-funding-rate-history-api/)
- [Freqtrade vs Hummingbot (Gainium)](https://gainium.io/compare/freqtrade-vs-hummingbot)
- [NautilusTrader comparison (pm.wiki)](https://pm.wiki/compare/nautilustrader-vs-polyrust)

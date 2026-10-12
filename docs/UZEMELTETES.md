# Üzemeltetési útmutató

Ez a leírás a napi használathoz kell, programozói tudás nélkül. Minden parancsot a Terminálba másolj be.
Az első sor mindig belép a repó mappájába (a mappanévben szóköz van, ezért idézőjelben).

## Mi fut magától a Mac minin

| Feladat | Mikor | Mit csinál | Napló |
|---|---|---|---|
| `com.evolutiontrader.recorder` | folyamatosan | percenként menti a Hyperliquid árakat, OI-t, fundingot | `~/Library/Logs/evolutiontrader/recorder.out.log` |
| `com.evolutiontrader.paper` | óránként :03-kor | Telegram-parancsok, élő paper könyvelése, őr (riasztás) | `logs/paper.log` |
| `com.evolutiontrader.daily` | naponta 02:00 | adat → bíró → riport → kutató → fejlesztő → létra, Telegram-összefoglaló | `logs/daily.log` |

Állapotuk:
```
launchctl list | grep evolutiontrader
```
Három sor kell. A második oszlop `0` (vagy a rögzítőnél `143` egy kézi újraindítás után) jó; más szám hibát jelez – nézd meg a naplót.

Feltétel: a Mac mini bekapcsolva, a felhasználó automatikusan bejelentkezik, a külső lemez csatolva.

## Mit kapsz Telegramon

- **Minden reggel** (02:00 után): a napi összefoglaló – L1-ítéletek, új hipotézisek és sorsuk, jóváhagyásra várók.
- **Riasztás** (⚠️), ha valami leállt: rögzítő, paper, napi futás, kevés hely a lemezen. Ugyanaz legfeljebb 6 óránként ismétlődik; ha megjavult, ✅ jön.

## Jóváhagyás (L2: élő paper, L3: mikro-éles)

A bíró csak az első szintig (L1) dönt egyedül. Feljebb csak a te jóváhagyásoddal lép stratégia.
Telegramon írd a botnak (legfeljebb egy órán belül végrehajtja):

| Parancs | Hatás |
|---|---|
| `/waiting` | a jóváhagyásra várók listája (DSR, PBO, PF 2x költségnél, OOS/IS, a hipotézis egy mondatban) |
| `/approve <azonosító>` | egy szinttel feljebb (L1 → L2: élő paper indul) |
| `/reject <azonosító> <ok>` | a várólistáról elutasítva |
| `/status` | rövid állapot |

Ugyanez Terminálból:
```
cd "/Volumes/Mac Nvme Extended/Github/evolutiontrader" && uv run evolab approve <azonosító>
```
A várólista 14 nap után lejár. Visszaléptetés (pl. rossz paper-eredmény) automatikus, arról értesítést kapsz.

## Dashboard és riport

```
open "/Volumes/Mac Nvme Extended/Github/evolutiontrader/reports/index.html"
```
A napi riport szövegesen: `reports/ÉÉÉÉ-HH-NN.md`. Kézi frissítés: `uv run evolab report`.

## Vészleállítás (STOP)

A paper-könyvelés és a fejlesztő (új kód írása) leáll, a rögzítő tovább fut:
```
cd "/Volumes/Mac Nvme Extended/Github/evolutiontrader" && touch STOP
```
Visszakapcsolás:
```
cd "/Volumes/Mac Nvme Extended/Github/evolutiontrader" && rm STOP
```

## Ha valami nem működik

1. Állapot és riasztások most:
   ```
   cd "/Volumes/Mac Nvme Extended/Github/evolutiontrader" && uv run evolab watchdog --dry-run && uv run evolab status
   ```
2. A háttérfeladatok újratelepítése (mindhárom):
   ```
   cd "/Volumes/Mac Nvme Extended/Github/evolutiontrader" && bash ops/install-launchd.sh
   ```
3. Napi futás kézzel (pl. ha a gép éjjel ki volt kapcsolva):
   ```
   cd "/Volumes/Mac Nvme Extended/Github/evolutiontrader" && uv run evolab daily
   ```
4. A Claude Code bejelentkezés lejárt (a napi üzenetben „Claude-hiba” a kutatónál/fejlesztőnél): nyisd meg a Terminált, írd be `claude`, jelentkezz be, majd lépj ki.
5. Teljes ellenőrzés: `make verify-all`.

## Mit ne csinálj

- Ne válts git-ágat a fő mappában (a háttérfeladatok onnan futnak). A fejlesztő külön mappában (`data/worktrees/`) dolgozik.
- A `config/judge.yaml` (a bíró küszöbei) csak dátumozott, tudatos döntéssel változhat – a döntésnapló: `docs/DONTESEK.md`.
- A `data/` mappát ne töröld: benne van minden letöltött adat, a kísérletnapló (`lab.db`) és a paper-történet. Mentése: Time Machine.

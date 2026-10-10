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

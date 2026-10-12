"""
family: volbreak
hypothesis_id: H-2026-10-12-03
parent_id: volbreak-squeeze-4h-04
hypothesis: >
  A szűkülés utáni kitörés egy volatilitás-tágulási szakasz kezdete. Ennek első gyertyáiban a
  realizált ingás nagy, de a szűkülés idején mért ATR még kicsi, így a 2.5-szeres ATR-stop szűk. A
  korai, zajos visszahúzásokra kiütött pozíciók újabb belépést és kétszeres költséget hoznak, és
  ezt a szerkezeti zajt a rövid távú likviditásnyújtók aratják le. Szélesebb stoppal kevesebb lesz
  a hamis kiszállás és a kötésszám, a pozíció pedig a tágulási trend nagyobb részét tartja meg. Ez
  közvetlenül a szülő gyenge pontját, a 2x költségnél mért PF-et (1.20) célozza.
expected_regimes: [up/mid, down/mid, up/high, down/high]
falsifier: >
  Cáfolt, ha egyik rácspontnál sem csökken a kötésszám legalább 15%-kal a szülőhöz képest, vagy ha
  egyik rácspont PF-je sem éri el 2x költségnél az 1.25-öt, vagy ha a paraméter-stabilitási
  vizsgálatban (atr_stop ±20%) bármely szomszédos beállítás negatív hozamú.
"""


from evolab.strategy import lib

TIMEFRAME = "4h"
PARAMS = {'bb_n': 40, 'bb_k': 2.0, 'pct_window': 250, 'squeeze_pct': 20, 'squeeze_lookback': 6, 'atr_n': 14, 'atr_stop': 3}


def signals(bars, regime, params):
    return lib.per_symbol(bars, lambda d, p, reg: lib.squeeze_breakout_signal(d, p), params, regime)

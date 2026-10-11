"""
family: positioning
hypothesis_id: H-seed-pos-contrarian
hypothesis: >
  Szélsőséges pozícionáltságnál (funding z-score abszolút értéke nagy, OI nő) a zsúfolt oldal
  sérülékeny: a finanszírozási költség és a likvidációs kockázat miatt a pozíciók leépítése
  valószínű, ami az árat a zsúfolt iránnyal szemben mozgatja. A kontrariánus jel ezt a leépülést
  próbálja elkapni, rövid tartással, ATR-stoppal védve a folytatódó trend ellen.
expected_regimes: [up/high, down/high, flat/high]
falsifier: >
  Ha a zsúfoltság után az ár többnyire a zsúfolt irányba megy tovább (a trend erősebb a
  leépülésnél), és 2x költségnél a PF 1,0 alatt van, a hipotézis megbukott.
"""

from evolab.strategy import lib

TIMEFRAME = "4h"
PARAMS = {'fz_days': 30, 'fz_thr': 2.0, 'fz_exit': 0.5, 'oi_days': 7, 'atr_n': 14, 'atr_stop': 2.0}


def signals(bars, regime, params):
    return lib.per_symbol(bars, lambda d, p, reg: lib.contrarian_signal(d, p), params, regime)

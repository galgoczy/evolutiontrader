"""
family: positioning
hypothesis_id: H-seed-pos-filter
hypothesis: >
  A funding-ráta és az open interest a perpetual piac pozícionáltságát méri: ha a funding
  szokatlanul magas és az OI nő, a long oldal zsúfolt, a további vevők elfogytak, és egy kis esés
  likvidációs kaszkádot indíthat. Szűrőként a trendjelen ez azt jelenti, hogy a zsúfolt irányba
  nem lépünk be, így a trendkövetés a legrosszabb, kifulladó szakaszokat kihagyja.
expected_regimes: [up/high, down/high, up/mid, down/mid]
falsifier: >
  Ha a szűrt változat nem jobb a szűretlen trendjelnél (PF, DD), vagy a szűrés a nyereséges
  kötéseket is kiveszi, a hipotézis megbukott.
"""

from evolab.strategy import lib

TIMEFRAME = "4h"
PARAMS = {'core': 'donchian', 'n': 55, 'fz_days': 30, 'fz_thr': 1.5, 'oi_days': 7, 'atr_n': 14, 'atr_stop': 3.0}


def signals(bars, regime, params):
    return lib.per_symbol(bars, lambda d, p, reg: lib.filtered_trend_signal(d, p), params, regime)

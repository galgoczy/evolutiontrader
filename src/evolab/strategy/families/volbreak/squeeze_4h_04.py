"""
family: volbreak
hypothesis_id: H-seed-volbreak-squeeze
hypothesis: >
  A volatilitás csoportosul és átlaghoz tér vissza: egy szokatlanul szűk Bollinger-sáv (alacsony
  realizált vol) után nagyobb mozgás következik. Ha a szűkülés után az ár a sávon kívülre zár, a
  felgyűlt stop-megbízások és a vol-célzó szereplők pozícióépítése az irányt felerősíti. A
  középvonal visszakeresztezése jelzi, hogy a kitörés elhalt.
expected_regimes: [up/low, down/low, flat/low, up/mid]
falsifier: >
  Ha a szűkülés utáni kitörések várható értéke nem jobb, mint a szűkülés nélkülieké, vagy 2x
  költségnél a PF 1,0 alatt van, a hipotézis megbukott.
"""

from evolab.strategy import lib

TIMEFRAME = "4h"
PARAMS = {'bb_n': 40, 'bb_k': 2.0, 'pct_window': 250, 'squeeze_pct': 20, 'squeeze_lookback': 6, 'atr_n': 14, 'atr_stop': 2.5}


def signals(bars, regime, params):
    return lib.per_symbol(bars, lambda d, p, reg: lib.squeeze_breakout_signal(d, p), params, regime)

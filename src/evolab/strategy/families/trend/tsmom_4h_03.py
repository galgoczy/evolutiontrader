"""
family: trend
hypothesis_id: H-seed-trend-tsmom
hypothesis: >
  Az idősoros momentum (a saját múltbeli hozam előjele mint jel) Moskowitz–Ooi–Pedersen óta számos
  eszközosztályon igazolt, és a kriptó-irodalom (Liu–Tsyvinski) szerint a kriptóban erősebb, mint
  a részvényeken. A mechanizmus a lassú információterjedés és a befektetői figyelem késése; a jel
  egyszerű, kevés paramétere miatt nehezen illeszthető túl.
expected_regimes: [up/high, up/mid, down/high, down/mid]
falsifier: >
  Ha a 20/60/120 gyertyás változatok közül egyik sem marad pozitív 2x költségnél, vagy csak
  egyetlen lookback működik, a hipotézis megbukott.
"""

from evolab.strategy import lib

TIMEFRAME = "4h"
PARAMS = {'core': 'tsmom', 'lookback': 120, 'atr_n': 14, 'atr_stop': 3.0}


def signals(bars, regime, params):
    return lib.per_symbol(bars, lambda d, p, reg: lib.trend_signal(d, p), params, regime)

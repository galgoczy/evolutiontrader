"""
family: relstrength
hypothesis_id: H-seed-relstr-ethbtc
hypothesis: >
  Az ETH/BTC árfolyamarány hosszú távon kointegráltnak tekinthető, mert a két eszköz kockázati
  faktora közös, és a rotáció (tőke áramlása a kettő között) időleges. A log-arány szélsőséges
  z-score-ja túllövést jelez, ami a két láb (egyik long, másik short) piacsemleges pozíciójával
  kihasználható, a közös piaci iránytól függetlenül.
expected_regimes: [flat/low, flat/mid, up/mid, down/mid]
falsifier: >
  Ha a z-score szélsőértékei után az arány nem tér vissza (tartós rezsimváltás, pl. ETH saját
  narratívája), és a PF 2x költségnél 1,0 alatt van, a hipotézis megbukott.
"""

from evolab.strategy import lib

TIMEFRAME = "4h"
PARAMS = {'leg_a': 'ETHUSDT', 'leg_b': 'BTCUSDT', 'z_window': 60, 'z_entry': 2.0, 'z_exit': 0.5}


def signals(bars, regime, params):
    return lib.pair_reversion_signal(bars, params)

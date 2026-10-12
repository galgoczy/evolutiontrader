"""
family: relstrength
hypothesis_id: H-seed-relstr-soleth
hypothesis: >
  A SOL/ETH arány a két legnagyobb okosszerződés-platform relatív értékelése; rövid távú eltérései
  gyakran hírvezéreltek és túlreagáltak, mert a kisebb likviditású SOL-ban a tőkeáttétes pozíciók
  gyorsabban épülnek és bomlanak le. A log-arány szélsőséges z-score-ja után az átlaghoz való
  visszatérés piacsemleges, kétlábú pozícióval aknázható ki.
expected_regimes: [flat/mid, flat/high, up/high, down/high]
falsifier: >
  Ha a SOL/ETH arány trendje (pl. 2021, 2023) tartósan elviszi a pozíciót és a nyereség nem éli
  túl a 2x költséget, a hipotézis megbukott.
"""

from evolab.strategy import lib

TIMEFRAME = "4h"
PARAMS = {'leg_a': 'SOLUSDT', 'leg_b': 'ETHUSDT', 'z_window': 60, 'z_entry': 2.0, 'z_exit': 0.5}


def signals(bars, regime, params):
    return lib.pair_reversion_signal(bars, params)

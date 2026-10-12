"""
family: trend
hypothesis_id: H-seed-trend-donchian
hypothesis: >
  A csatornakitörés (Donchian) a trendkövetés legrégebbi, a tőzsdei teknős-kísérletben is igazolt
  formája: ha az ár a megelőző n gyertya csúcsa fölé zár, a kínálati oldal kimerült, és a stop-
  megbízások, likvidációk lavinája tovább viszi az árat. Kriptóban a magas tőkeáttét miatt ez a
  lavina-hatás erősebb, mint a hagyományos piacokon, így a kitörés utáni folytatás valószínűbb.
expected_regimes: [up/high, down/high, up/mid, down/mid]
falsifier: >
  Ha a kitörések többsége 1-2 gyertyán belül visszafordul (hamis kitörés) és 2x költségnél a PF
  1,0 alá esik, a hipotézis megbukott.
"""

from evolab.strategy import lib

TIMEFRAME = "4h"
PARAMS = {'core': 'donchian', 'n': 55, 'atr_n': 14, 'atr_stop': 3.0}


def signals(bars, regime, params):
    return lib.per_symbol(bars, lambda d, p, reg: lib.trend_signal(d, p), params, regime)

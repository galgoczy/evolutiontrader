"""
family: rangerev
hypothesis_id: H-seed-rangerev-bb
hypothesis: >
  Trend nélküli (ADX alacsony, flat címke) piacon az ár egy sávban mozog, és a Bollinger-sáv
  széleinek átlépése túllövés, amit a piacjegyzők és a középtávú szereplők visszatolnak az
  átlaghoz. A stratégia csak flat címke alatt aktív, mert trendben a sávszél átlépése a folytatás
  jele, nem a visszatérésé.
expected_regimes: [flat/low, flat/mid, flat/high]
falsifier: >
  Ha flat címke alatt a sávszél utáni visszatérés várható értéke negatív, vagy a veszteség a
  címkeváltás körüli napokból jön (késő kilépés), a hipotézis megbukott.
"""

from evolab.strategy import lib

TIMEFRAME = "4h"
PARAMS = {'bb_n': 30, 'bb_k': 2.0, 'atr_n': 14, 'atr_stop': 2.0}


def signals(bars, regime, params):
    return lib.per_symbol(bars, lambda d, p, reg: lib.range_reversion_signal(d, p, reg), params, regime)

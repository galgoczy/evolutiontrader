"""
family: trend
hypothesis_id: H-seed-trend-ema
hypothesis: >
  A kriptó perpetual piacokon az idősoros momentum a legjobban dokumentált anomália: a hozamok
  napos-hetes távon pozitívan autokorrelálnak, mert az információ lassan terjed, a tőkeáttétes
  szereplők kényszerlikvidációi és a funding-vezérelt pozícióépítés felerősítik a már elindult
  mozgást. Egy gyors és egy lassú EMA keresztezése ezt a tartós irányt követi, az ATR-alapú követő
  stop a trend végén visszaadott nyereséget vágja le.
expected_regimes: [up/high, up/mid, down/high, down/mid]
falsifier: >
  Ha 2x költség mellett a profit factor 1,0 alatt marad, vagy a nyereség egyetlen rezsimből jön, a
  hipotézis megbukott; oldalazó (flat) piacon várható veszteség.
"""

from evolab.strategy import lib

TIMEFRAME = "4h"
PARAMS = {'core': 'ema', 'fast': 50, 'slow': 200, 'atr_n': 14, 'atr_stop': 3.0}


def signals(bars, regime, params):
    return lib.per_symbol(bars, lambda d, p, reg: lib.trend_signal(d, p), params, regime)

"""
family: trend
hypothesis: >
  A kriptó perpetual piacokon az idősoros momentum a legjobban dokumentált anomália: a hozamok
  napos-hetes távon pozitívan autokorrelálnak, mert az információ lassan terjed, a tőkeáttétes
  szereplők kényszerlikvidációi és a funding-vezérelt pozícióépítés felerősítik a már elindult
  mozgást. Egy lassú és egy gyors EMA keresztezése ezt a tartós irányt követi, az ATR-alapú
  követő stop pedig levágja a trend végén a visszaadott nyereség nagy részét. A jel minden coinon
  ugyanaz, a méretezést a szimulátor vol-céllal végzi.
expected_regimes: [up/high, up/mid, down/high, down/mid]
falsifier: >
  Ha 2x költség mellett a profit factor 1,0 alatt marad, vagy a nyereség egyetlen rezsimből
  (pl. csak up/high) jön, a hipotézis megbukott; oldalazó (flat) piacon várható veszteség.
"""

import pandas as pd

from evolab.features.indicators import atr, ema

TIMEFRAME = "4h"
PARAMS = {"fast": 20, "slow": 100, "atr_n": 14, "atr_stop": 3.0}


def _one(d: pd.DataFrame, p: dict) -> pd.DataFrame:
    c = d["close"]
    fast, slow = ema(c, p["fast"]), ema(c, p["slow"])
    target = (fast > slow).astype(float) - (fast < slow).astype(float)
    target = target.where(slow.notna(), 0.0)
    a = atr(d, p["atr_n"])
    # követő stop: egy-egy irányú szakaszon belül csak a pozíció javára mozdulhat
    run = (target != target.shift()).cumsum()
    long_stop = (c - p["atr_stop"] * a).groupby(run).cummax()
    short_stop = (c + p["atr_stop"] * a).groupby(run).cummin()
    stop = long_stop.where(target > 0, short_stop.where(target < 0))
    reason = target.map({1.0: "ema_fast>slow", -1.0: "ema_fast<slow", 0.0: ""})
    return pd.DataFrame({"target_position": target, "stop_price": stop, "reason": reason})


def signals(bars: pd.DataFrame, regime: pd.DataFrame, params: dict) -> pd.DataFrame:
    return pd.concat([_one(d, params) for _, d in bars.groupby(level="symbol", sort=False)])

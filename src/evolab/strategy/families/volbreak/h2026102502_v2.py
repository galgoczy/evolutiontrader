"""
family: volbreak
hypothesis_id: H-2026-10-25-02
parent_id: volbreak-h2026101203-v2
hypothesis: >
  A Bollinger-szűkülés kétféle helyzetben jöhet létre. (1) Valódi konszolidáció egy oldalazó
  szakasz végén: a range két szélén stopok és függő megbízások gyűlnek, a kitörés ezeket egymás
  után kiüti, és a pozícionálás átrendeződése új trendet indít. (2) Szünet egy már futó trend
  közepén: itt a szűkülés csak a trend kifulladása vagy pihenője, a sávátlépések rövidek, és a
  trendkövetők már pozícióban vannak, így nincs friss, kényszerű áramlás, ami a kitörést vinné. Az
  első esetben a vesztes oldal a range-ben rossz irányba pozícionált és stopolt szereplő, a
  másodikban nincs ilyen szereplő, a kitörés zajba fut és költséget termel. Az előző napi flat
  címke az első helyzetet jelöli ki, ezért a szülő kitörésjele csak allowed_trend címke alatt kap
  új belépést; a nyitott pozíció és ATR-trailing stopja a szülő szerint fut tovább.
expected_regimes: [flat/low, flat/mid]
falsifier: >
  Elvetjük, ha a flat címke alatti kitörések átlagos kötésenkénti hozama (költség után) nem
  nagyobb legalább 20%-kal, mint az up/down címke alattiaké a szülő teljes visszatesztjén, VAGY ha
  a kötésszám 100 alá esik, VAGY egyik változat PF-je sem éri el 2x költségnél az 1,30-at.
"""


import pandas as pd

from evolab.strategy import lib

TIMEFRAME = "4h"
PARAMS = {'bb_n': 40, 'bb_k': 2.0, 'pct_window': 250, 'squeeze_pct': 20, 'squeeze_lookback': 6, 'atr_n': 14, 'atr_stop': 4, 'allowed_trend': ['flat', 'up']}


def _gated(d, p, reg):
    sig = lib.squeeze_breakout_signal(d, p)
    t = sig["target_position"]
    trend_ok = reg["trend"].isin(list(p["allowed_trend"])) if reg is not None else pd.Series(False, index=d.index)
    # egy azonos irányú szakasz sorsát a belépő gyertya (előző napi) címkéje dönti el
    run = (t != t.shift()).cumsum()
    keep = trend_ok.reindex(d.index).fillna(False).astype(bool).groupby(run).transform("first")
    return lib.condition(sig, keep | (t == 0), "trend_gate")


def signals(bars, regime, params):
    return lib.per_symbol(bars, _gated, params, regime)

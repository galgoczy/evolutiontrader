"""
family: volbreak
hypothesis_id: H-2026-11-09-03
parent_id: volbreak-h2026110801-v2
hypothesis: >
  A szűkülés utáni kitörés éle abból fakad, hogy a tartomány rossz oldalán álló pozíciók
  kényszerű zárása és az új, kitörést követő tőke friss keresletet ad. Ha viszont a kitörés
  irányában a funding már szélsőségesen magas, a tőkeáttételes vevők jó része már bent van: a
  kitöréshez nincs elég új marginális vevő, a longok drága carry-t fizetnek, és a zsúfolt állomány
  az első visszaesésnél likvidációs láncot indíthat ellenirányba. A veszítő oldal itt mi lennénk:
  a késve, zsúfolt oldalra belépő kitöréskövető. A szülő már használ funding-alapú
  profitrealizálást a kilépésnél; ez ugyanazt a mechanizmust a belépésre alkalmazza. A szülő új
  belépésének gyertyáján: felfelé kitörés nem nyit longot, ha funding_z(fz_days) > fz_crowd; lefelé
  kitörés nem nyit shortot, ha funding_z < -fz_crowd. Hiányzó funding-adatnál nincs tiltás. A
  tiltott kitörést később sem pótoljuk; a szülő teljes láncolata (rezsimfeltétel, bb_mid-igazítás,
  BTC-tiltás, BTC-szűkülés kizárás, ATR-trailing, funding-realizálás) változatlan.
expected_regimes: [up/mid, flat/mid, flat/low, up/high]
falsifier: >
  Elvetjük, ha a kiszűrt (zsúfolt oldali) kitörések a szülőben 2x költség mellett PF >= 1.3-at
  hoztak volna, vagy ha egyik variánsnál sem javul a szülőhöz képest a PF 2x költségnél, illetve
  ha a PBO >= 0.2 vagy a kötésszám 100 alá esik.
"""


import numpy as np

from evolab.strategy import lib

TIMEFRAME = "4h"
PARAMS = {'bb_n': 40, 'bb_k': 2.0, 'pct_window': 250, 'squeeze_pct': 20, 'squeeze_lookback': 6, 'atr_n': 14, 'atr_stop': 4, 'allowed_trend': ['flat', 'up'], 'fz_days': 30, 'fz_take': 2, 'take_atr': 1.0, 'short_allowed': ['flat'], 'btc_block_mode': 'both', 'fz_against': 2, 'align_mode': 'bb_mid', 'btc_sq_mode': 'exclude', 'btc_sq_lookback': 6, 'fz_crowd': 1.5}

# a szülő teljes láncolata a volbreak-h2026110801-v2 jele; erre jön a zsúfolt oldali belépés tiltása
PARENT = "volbreak-h2026110801-v2"


def _gate(d, p, base):
    sig = base.loc[d.index]
    side = np.sign(sig["target_position"])
    start = side != side.shift()
    run = start.cumsum()

    # a döntés a szakasz elején (belépő gyertya) születik; hiányzó funding-z -> nincs tiltás
    z = lib.funding_z(d, p["fz_days"])
    z0 = z.where(start).groupby(run).ffill()
    block_long = (side > 0) & (z0 > p["fz_crowd"])
    block_short = (side < 0) & (z0 < -p["fz_crowd"])
    out = lib.block_direction(sig, block_long, block_short)
    out.loc[block_long | block_short, "reason"] = ""
    return out


def signals(bars, regime, params):
    base_p = {k: v for k, v in params.items() if k != "fz_crowd"}
    base = lib.parent_signals(PARENT, bars, regime, base_p)
    return lib.per_symbol(bars, lambda d, p, reg: _gate(d, p, base), params)

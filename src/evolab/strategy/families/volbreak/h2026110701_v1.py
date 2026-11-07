"""
family: volbreak
hypothesis_id: H-2026-11-07-01
parent_id: volbreak-h2026110602-v1
hypothesis: >
  Széles piaci esésben (BTC és az altcoin is down) az altcoin-szűkülésből lefelé kitörést a
  tőkeáttételes longok kényszerzárása és a korrelált kockázatcsökkentés hajtja: a margin-hívásba
  kerülő long oldal piaci áron ad el, ez folytatást okoz. Ennek a shortnak a fő kockázata a
  BTC-relief rally, amikor a zsúfolt shortok fedeznek és az altcoinok béta-szorzóval felrántódnak.
  A bb_mid igazítás pont ezeket a pillanatokat zárja ki: ha a BTC már a saját középvonala fölé
  pattant, az altcoin lefelé kitörése valószínűleg csapda. A két módosítás tehát egymás gyenge
  pontját fedi: a down/down bővítés több eseményt ad a nyerő oldalon, az igazítás kiszűri a
  squeeze-veszélyes eseteket. Elsőbbségi sorrend: (1) a coin rezsimfeltétele (long flat/up, short
  flat) a down/down bővítéssel (a BTCUSDT saját down-shortja csak btc_short_down esetén),
  (2) a funding-felülbírálat (fz_against 2) csak a még tiltott eseteket oldja fel, (3) altcoinokra a
  4h-s bb_mid igazítás (BTCUSDT zárása a bb_n középvonal fölött/alatt), (4) a napi BTC-vezető tiltás
  (both) utolsó lépésként. A tiltott kitörést később sem pótoljuk; a nyitott pozíció, az ATR-trailing
  és a funding-alapú profitrealizálás a szülőé.
expected_regimes: [down/mid, down/high, flat/low, flat/mid, up/mid]
falsifier: >
  Elvetjük, ha (a) a down/down bővítésből származó többlet-shortok PF-je 2x költségnél < 1.0, vagy
  (b) a variáns PF 2x költségnél több mint 0.15-tel elmarad a szülő 1.77-étől, vagy (c) PBO >= 0.2,
  vagy (d) a többlet-kötések száma < 15 (nincs érdemi új információ).
"""


import numpy as np
import pandas as pd

from evolab.strategy import lib

TIMEFRAME = "4h"
PARAMS = {'bb_n': 40, 'bb_k': 2.0, 'pct_window': 250, 'squeeze_pct': 20, 'squeeze_lookback': 6, 'atr_n': 14, 'atr_stop': 4, 'allowed_trend': ['flat', 'up'], 'fz_days': 30, 'fz_take': 2, 'take_atr': 1.0, 'short_allowed': ['flat'], 'btc_block_mode': 'both', 'fz_against': 2, 'align_mode': 'bb_mid', 'btc_short_down': True}

# a kitörés + ATR-trailing + funding-realizálás a volbreak-h2026102601-v1 jele, címkeszűrés nélkül;
# a rezsimfeltételt (down/down bővítéssel), a funding-felülbírálatot, a 4h-s BTC-igazítást és a
# napi BTC-vezető tiltást itt alkalmazzuk
BASE = "volbreak-h2026102601-v1"
BTC = "BTCUSDT"
ALL_TRENDS = ["flat", "up", "down"]


def _btc_align(btc_bars, p):
    """A BTC gyertyaszintű iránya (+1/-1, egyébként 0) a gyertya zárásáig ismert árból."""
    if btc_bars.empty:
        return pd.Series(dtype=float, index=pd.Index([], dtype="int64"))
    c = btc_bars["close"]
    if p["align_mode"] == "bb_mid":
        a = np.sign(c - c.rolling(p["bb_n"]).mean()).fillna(0.0)
    else:
        a = lib.tsmom(btc_bars, 20)
    return a


def _gate(d, p, reg, base, btc_trend, btc_align):
    sig = base.loc[d.index]
    t = sig["target_position"]
    run = (t != t.shift()).cumsum()
    is_btc = d.index.get_level_values("symbol")[0] == BTC

    # a coin és a BTC (előző napi) címkéje; BTC-gyertya hiányakor az utolsó ismert címke
    own = reg["trend"].reindex(d.index) if reg is not None else pd.Series(index=d.index, dtype=object)
    ts = d.index.get_level_values("ts")
    btc = own if is_btc else pd.Series(btc_trend.reindex(ts, method="ffill").to_numpy(), index=d.index)
    z = lib.funding_z(d, p["fz_days"])

    # (1) a coin rezsimfeltétele a down/down short-bővítéssel
    long_rule = own.isin(list(p["allowed_trend"]))
    short_flat = own.isin(list(p["short_allowed"]))
    down_short = (own == "down") & (btc == "down")
    if is_btc and not p["btc_short_down"]:
        down_short = pd.Series(False, index=d.index)
    # (2) funding-felülbírálat: a kitöréssel ellentétes oldal zsúfolt (a gyertya zárásáig ismert funding-z)
    long_override = (own == "down") & (z < -p["fz_against"])
    short_override = own.isin(["up", "down"]) & (z > p["fz_against"])

    # a döntés a szakasz elején (belépő gyertya) születik, a nyitott pozíciót később nem érinti
    first = lambda s: s.fillna(False).astype(bool).groupby(run).transform("first")
    lr, lo = first(long_rule), first(long_override)
    sf, ds, so = first(short_flat), first(down_short), first(short_override)
    block_long = ~(lr | lo)
    block_short = ~(sf | ds | so)

    if not is_btc:
        # (3) 4h-s BTC-igazítás: long csak BTC középvonal fölött, short csak alatta
        if not btc_align.empty:
            align = pd.Series(btc_align.reindex(ts, method="ffill").to_numpy(), index=d.index)
            block_long = block_long | first(align != 1)
            block_short = block_short | first(align != -1)
        # (4) napi BTC-vezető tiltás utolsó lépésként (both: a short is tiltott BTC up alatt)
        block_long = block_long | first(btc == "down")
        block_short = block_short | (first(btc == "up") & (p["btc_block_mode"] == "both"))
    out = lib.block_direction(sig, block_long, block_short)
    out.loc[((t > 0) & block_long) | ((t < 0) & block_short), "reason"] = ""
    live = out["target_position"]
    out.loc[(live > 0) & ~lr & lo, "reason"] = "squeeze_break_up|crowd_override"
    out.loc[(live < 0) & ~sf & ds, "reason"] = "squeeze_break_down|btc_down_short"
    out.loc[(live < 0) & ~sf & ~ds & so, "reason"] = "squeeze_break_down|crowd_override"
    return out


def signals(bars, regime, params):
    drop = ("short_allowed", "btc_block_mode", "fz_against", "btc_short_down", "align_mode")
    base_p = {k: v for k, v in params.items() if k not in drop}
    base = lib.parent_signals(BASE, bars, regime, {**base_p, "allowed_trend": ALL_TRENDS})
    has_btc = regime is not None and BTC in regime.index.get_level_values("symbol")
    btc_trend = regime.xs(BTC, level="symbol")["trend"].sort_index() if has_btc else pd.Series(dtype=object, index=pd.Index([], dtype="int64"))
    btc_bars = bars.xs(BTC, level="symbol").sort_index() if BTC in bars.index.get_level_values("symbol") else bars.iloc[:0]
    btc_align = _btc_align(btc_bars, params)
    return lib.per_symbol(bars, lambda d, p, reg: _gate(d, p, reg, base, btc_trend, btc_align), params, regime)

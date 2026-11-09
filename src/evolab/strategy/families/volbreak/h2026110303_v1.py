"""
family: volbreak
hypothesis_id: H-2026-11-03-03
parent_id: volbreak-h2026110202-v2
hypothesis: >
  Piaci tényezővel bővített short-feltétel. Ha az egész piac rendszerszintű tőkeáttétel-leépítésben
  van (a BTC is down), az altcoin szűkülés utáni lefelé törése nem izolált zaj. A kockázatcsökkentő
  alapok és a margin-hívást kapó long-perp tartók együtt adnak el, és a magasabb bétájú altcoinokat
  sújtja leginkább a kényszerű eladás. Ilyenkor a szűkülés csak a likvidálási hullámok közti szünet.
  A kitörés alatt a vételi oldalon a késve belépő bottom-vásárlók és a range-árjegyzők veszítenek.
  A szülő a down rezsimet teljesen tiltja, mert izolált down címkénél (BTC flat vagy up) az
  alt-shortok a piaci visszahúzás miatt rosszak; a BTC-egyezés szétválasztja a két esetet. Az
  altcoin short belépése a coin előző napi flat címkéje mellett akkor is érvényes, ha a coin és a
  BTCUSDT előző napi címkéje is down. A BTCUSDT saját shortja down címke alatt csak btc_short_down
  esetén nyílhat. A long-feltétel (flat, up) és a BTC-vezető tiltás (both) változatlan; a tiltott
  kitörés nem nyit és később sem pótoljuk. A nyitott pozíció, az ATR-trailing és a funding-alapú
  profitrealizálás a szülőé.
expected_regimes: [down/mid, down/high, flat/low]
falsifier: >
  Elvetjük, ha az új (coin down + BTC down) feltétellel nyitott short-kötések átlagos nettó hozama
  2x költségnél <= 0, vagy ha a variáns PF-je 2x költségnél < 1.67 (szülő). Elvetjük akkor is, ha a
  PBO >= 0.2, vagy ha az OOS/IS < 0.5.
"""


import pandas as pd

from evolab.strategy import lib

TIMEFRAME = "4h"
PARAMS = {'bb_n': 40, 'bb_k': 2.0, 'pct_window': 250, 'squeeze_pct': 20, 'squeeze_lookback': 6, 'atr_n': 14, 'atr_stop': 4, 'allowed_trend': ['flat', 'up'], 'fz_days': 30, 'fz_take': 2, 'take_atr': 1.0, 'short_allowed': ['flat'], 'btc_block_mode': 'both', 'btc_short_down': True}

# a kitörés + ATR-trailing + funding-realizálás a volbreak-h2026102601-v1 jele, címkeszűrés nélkül;
# a rezsimfeltételt (irányonként) és a BTC-vezető tiltást itt alkalmazzuk
BASE = "volbreak-h2026102601-v1"
BTC = "BTCUSDT"
ALL_TRENDS = ["flat", "up", "down"]


def _gate(d, p, reg, base, btc_trend):
    sig = base.loc[d.index]
    t = sig["target_position"]
    run = (t != t.shift()).cumsum()
    is_btc = d.index.get_level_values("symbol")[0] == BTC

    # a coin és a BTC (előző napi) címkéje; BTC-gyertya hiányakor az utolsó ismert címke
    own = reg["trend"].reindex(d.index) if reg is not None else pd.Series(index=d.index, dtype=object)
    ts = d.index.get_level_values("ts")
    btc = own if is_btc else pd.Series(btc_trend.reindex(ts, method="ffill").to_numpy(), index=d.index)

    # a döntés a szakasz elején születik, a nyitott pozíciót a címke későbbi váltása nem érinti
    long_ok = own.isin(list(p["allowed_trend"]))
    down_short = (own == "down") & (btc == "down")
    if is_btc and not p["btc_short_down"]:
        down_short = pd.Series(False, index=d.index)
    short_ok = own.isin(list(p["short_allowed"])) | down_short
    first = lambda s: s.fillna(False).astype(bool).groupby(run).transform("first")
    long_ok, short_ok, new_short = first(long_ok), first(short_ok), first(down_short & ~own.isin(list(p["short_allowed"])))

    # BTC-vezető tiltás csak altcoinokra (both: a short is tiltott BTC up alatt)
    block_long = ~long_ok
    block_short = ~short_ok
    if not is_btc:
        block_long = block_long | first(btc == "down")
        block_short = block_short | (first(btc == "up") & (p["btc_block_mode"] == "both"))
    out = lib.block_direction(sig, block_long, block_short)
    out.loc[((t > 0) & block_long) | ((t < 0) & block_short), "reason"] = ""
    out.loc[(out["target_position"] < 0) & new_short, "reason"] = out["reason"].astype(str) + "|btc_down_short"
    return out


def signals(bars, regime, params):
    base_p = {k: v for k, v in params.items() if k not in ("short_allowed", "btc_block_mode", "btc_short_down")}
    base = lib.parent_signals(BASE, bars, regime, {**base_p, "allowed_trend": ALL_TRENDS})
    has_btc = regime is not None and BTC in regime.index.get_level_values("symbol")
    btc_trend = regime.xs(BTC, level="symbol")["trend"].sort_index() if has_btc else pd.Series(dtype=object, index=pd.Index([], dtype="int64"))
    return lib.per_symbol(bars, lambda d, p, reg: _gate(d, p, reg, base, btc_trend), params, regime)

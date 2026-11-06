"""
family: volbreak
hypothesis_id: H-2026-11-06-02
parent_id: volbreak-h2026110301-v2
hypothesis: >
  Kriptóban az altcoinok hozamát nagyrészt a BTC piaci tényezője magyarázza (béta 1 fölött). Ha egy
  altcoin a BTC aktuális rövid távú irányával szemben tör ki, a mozgást jellemzően vékony,
  coin-specifikus kereslet hajtja. Amint a piaci tényező visszahúz, a kitörés elhal, a kitörésre
  vásárlók csapdába kerülnek, és őket a market makerek és arbitrázsőrök ellenoldala nyeri meg. Ha a
  kitörés egybeesik a BTC irányával, a mozgás mögött széles, keresztcoinos áramlás áll: indexszerű
  vásárlás vagy likvidációs kaszkád több könyvön egyszerre. Ez tartósabb, és a trailing stop jobban
  kifut. A meglévő napi címkén alapuló tiltás egy nap késéssel reagál; a 4h-s megerősítés a napon
  belüli tényező-ellentmondást szűri. Altcoin long csak akkor nyit, ha a BTCUSDT ugyanazon a 4h
  időbélyegen megerősít (bb_mid: zárás a bb_n Bollinger-középvonal fölött; tsmom_20: tsmom(20) > 0),
  short csak fordított esetben. A tiltott kitörést később sem pótoljuk. A napi BTC-vezető tiltás
  (both) megmarad utolsó lépésként; a BTC saját belépései, a nyitott pozíció, az ATR-trailing, a
  funding-alapú profitrealizálás, a rezsimfeltétel és a funding-felülbírálat a szülőé.
expected_regimes: [up/mid, flat/mid, down/mid]
falsifier: >
  Cáfolt, ha a szűrő által kizárt altcoin-kitörések átlagos kötésenkénti hozama a szülőben (költség
  után) nem rosszabb a megtartottakénál, vagy ha egyik variáns PF-je 2x költségnél sem haladja meg a
  szülőét (1.66), vagy ha a kötésszám 100 alá esik, vagy ha a PBO >= 0.2.
"""


import numpy as np
import pandas as pd

from evolab.strategy import lib

TIMEFRAME = "4h"
PARAMS = {'bb_n': 40, 'bb_k': 2.0, 'pct_window': 250, 'squeeze_pct': 20, 'squeeze_lookback': 6, 'atr_n': 14, 'atr_stop': 4, 'allowed_trend': ['flat', 'up'], 'fz_days': 30, 'fz_take': 2, 'take_atr': 1.0, 'short_allowed': ['flat'], 'btc_block_mode': 'both', 'fz_against': 2, 'align_mode': 'tsmom_20'}

# a coin saját rezsimfeltétele + funding-felülbírálat a volbreak-h2026102801-v1 jele (mint a szülőben);
# erre jön a 4h-s BTC-megerősítés, majd utolsó lépésként a szülő napi BTC-vezető tiltása
OVERRIDE = "volbreak-h2026102801-v1"
BTC = "BTCUSDT"


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


def _gate(d, p, base, btc_trend, btc_align):
    sig = base.loc[d.index]
    if d.index.get_level_values("symbol")[0] == BTC:
        return sig
    t = sig["target_position"]
    run = (t != t.shift()).cumsum()

    # a BTC 4h-s iránya és (előző napi) címkéje a coin gyertyáira; BTC-gyertya hiányakor az utolsó ismert
    ts = d.index.get_level_values("ts")
    trend = pd.Series(btc_trend.reindex(ts, method="ffill").to_numpy(), index=d.index)
    if btc_align.empty:
        no_long = no_short = pd.Series(False, index=d.index)
    else:
        align = pd.Series(btc_align.reindex(ts, method="ffill").to_numpy(), index=d.index)
        no_long, no_short = align != 1, align != -1

    # a döntés a szakasz elején (belépő gyertya) születik; a tiltott kitörés később sem nyílik meg
    first = lambda s: s.fillna(False).astype(bool).groupby(run).transform("first")
    block_long = first(no_long) | first(trend == "down")
    block_short = first(no_short) | (first(trend == "up") & (p["btc_block_mode"] == "both"))
    out = lib.block_direction(sig, block_long, block_short)
    out.loc[((t > 0) & block_long) | ((t < 0) & block_short), "reason"] = ""
    return out


def signals(bars, regime, params):
    base_p = {k: v for k, v in params.items() if k not in ("btc_block_mode", "align_mode")}
    base = lib.parent_signals(OVERRIDE, bars, regime, base_p)
    has_btc = regime is not None and BTC in regime.index.get_level_values("symbol")
    btc_trend = regime.xs(BTC, level="symbol")["trend"].sort_index() if has_btc else pd.Series(dtype=object, index=pd.Index([], dtype="int64"))
    btc_bars = bars.xs(BTC, level="symbol").sort_index() if BTC in bars.index.get_level_values("symbol") else bars.iloc[:0]
    btc_align = _btc_align(btc_bars, params)
    return lib.per_symbol(bars, lambda d, p, reg: _gate(d, p, base, btc_trend, btc_align), params)

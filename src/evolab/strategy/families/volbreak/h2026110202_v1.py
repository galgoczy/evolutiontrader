"""
family: volbreak
hypothesis_id: H-2026-11-02-02
parent_id: volbreak-h2026102701-v1
hypothesis: >
  Piaci vezető feltétel az altcoin-belépéseken. A kriptópiac altcoinjai erős BTC-béta alatt mozognak,
  és a piacszintű kockázatvállalást a BTC iránya vezeti. Ha a BTC csökkenő trendben van, a tőke és a
  fedezet az altcoinokból szivárog ki, a piacjegyzők lejjebb húzzák a kínálatukat, az altcoin-kitörés
  mögött pedig jórészt szűk, tőkeáttételes vevők állnak. Ők fizetnek rá: a saját coin-grafikont nézve
  belépnek a kitörésbe, majd a következő BTC-esésnél a közös tényező visszaviszi az árat. A coin saját
  trendcímkéje ezt nem fogja meg, mert egy altcoin lehet flat, miközben a tényezője már esik. A szűrő
  nem új belépési okot ad, csak a közös tényező ellen futó, kis követési valószínűségű kitöréseket
  veszi ki, és csak egy külső, a coin árától független feltételen át teszi, ezért kevés szabadsági
  fokot ad hozzá. Az ETH, SOL, BNB, XRP, DOGE új long belépése tiltott, ha a BTCUSDT előző napi címkéje
  down; a both változatban az új short belépés is tiltott, ha a címke up. A tiltott kitörés nem nyit
  pozíciót és később sem pótoljuk. A BTCUSDT saját belépései, a nyitott pozíció, az ATR-trailing és a
  funding-alapú profitrealizálás változatlan.
expected_regimes: [flat/low, flat/mid, up/mid, up/low]
falsifier: >
  Elvetendő, ha a kiszűrt altcoin-kitörések kötésenkénti átlaghozama 2x költséggel nem alacsonyabb a
  megtartottakénál, vagy ha a PBO >= 0.2, vagy ha a PF 2x költségnél nem javul a szülő 1.53-as
  értékéhez képest, vagy a kötésszám 100 alá esik.
"""


import pandas as pd

from evolab.strategy import lib

TIMEFRAME = "4h"
PARAMS = {'bb_n': 40, 'bb_k': 2.0, 'pct_window': 250, 'squeeze_pct': 20, 'squeeze_lookback': 6, 'atr_n': 14, 'atr_stop': 4, 'allowed_trend': ['flat', 'up'], 'fz_days': 30, 'fz_take': 2, 'take_atr': 1.0, 'short_allowed': ['flat'], 'btc_block_mode': 'long'}

PARENT = "volbreak-h2026102701-v1"
BTC = "BTCUSDT"


def _btc_gate(d, p, parent, btc_trend):
    sig = parent.loc[d.index]
    if d.index.get_level_values("symbol")[0] == BTC:
        return sig
    t = sig["target_position"]
    run = (t != t.shift()).cumsum()

    # a BTC (előző napi) címkéje a coin gyertyáira; BTC-gyertya hiányakor az utolsó ismert címke
    ts = d.index.get_level_values("ts")
    trend = pd.Series(btc_trend.reindex(ts, method="ffill").to_numpy(), index=d.index)

    # a döntés a szakasz elején születik: a tiltott kitörés egész szakasza kiesik, később nincs
    # pótlás, a nyitott pozíciót a címke későbbi váltása nem érinti
    block_long = (trend == "down").groupby(run).transform("first")
    block_short = (trend == "up").groupby(run).transform("first") & (p["btc_block_mode"] == "both")
    out = lib.block_direction(sig, block_long, block_short)
    out.loc[((t > 0) & block_long) | ((t < 0) & block_short), "reason"] = ""
    return out


def signals(bars, regime, params):
    # a szülő (volbreak-h2026102701-v1) jele változatlanul
    parent_p = {k: v for k, v in params.items() if k != "btc_block_mode"}
    parent = lib.parent_signals(PARENT, bars, regime, parent_p)
    has_btc = regime is not None and BTC in regime.index.get_level_values("symbol")
    btc_trend = regime.xs(BTC, level="symbol")["trend"].sort_index() if has_btc else pd.Series(dtype=object, index=pd.Index([], dtype="int64"))
    return lib.per_symbol(bars, lambda d, p, reg: _btc_gate(d, p, parent, btc_trend), params)

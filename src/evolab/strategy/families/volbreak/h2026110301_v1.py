"""
family: volbreak
hypothesis_id: H-2026-11-03-01
parent_id: volbreak-h2026110202-v2
hypothesis: >
  Két, külön-külön átment módosítás keresztezése, amelyek más-más vesztest céloznak, ezért a hatásuk
  összeadódhat. A BTC-vezető tiltás azokat az altcoin-kitöréseket szűri ki, ahol az altcoin a piaci
  tényezővel szemben mozdul: ilyenkor a keresztpiaci árjegyzők és a bázis-arbitrázsőrök a BTC
  irányába húzzák vissza az árat, és a kitörő gyakran rosszul jár. A funding-felülbírálat ezzel
  szemben új belépéseket ad hozzá: amikor egy oldal tőkeáttételes perp-pozíciói zsúfoltak, a velük
  szembeni kitörés likvidációs és stop-láncot indít, a zsúfolt oldal kényszerűen zár, és ez
  üzemanyagot ad a kitörésnek. A coin saját címkéje szerint tiltott rezsimben is érvényes a kitörés,
  ha az ellentétes oldal zsúfolt: felfelé kitörés down címke alatt, ha funding_z(30) < -fz_against,
  lefelé kitörés up vagy down címke alatt, ha funding_z(30) > +fz_against. A felülbírálat csak a coin
  saját trendcímkéjét írja felül, a piaci tényezőt nem: a BTC-vezető tiltás (both mód) mindig az
  utolsó lépés. Így a squeeze-eket a BTC-vel egy irányban engedi, a BTC ellen zajló, jellemzően
  gyorsan elhaló izolált squeeze-eket nem. A tiltott kitörést később sem pótoljuk; a nyitott pozíció,
  az ATR-trailing és a funding-alapú profitrealizálás a szülőé.
expected_regimes: [flat/low, flat/mid, down/mid, up/mid]
falsifier: >
  Elvetjük, ha egyik variáns sem éri el a PF 2x költségnél >= 1.67 értéket, azaz a szülőt
  (volbreak-h2026110202-v2). Elvetjük akkor is, ha a felülbírálattal nyitott pluszkötések átlagos
  nettó hozama 2x költségnél <= 0, vagy ha a PBO >= 0.2.
"""


import pandas as pd

from evolab.strategy import lib

TIMEFRAME = "4h"
PARAMS = {'bb_n': 40, 'bb_k': 2.0, 'pct_window': 250, 'squeeze_pct': 20, 'squeeze_lookback': 6, 'atr_n': 14, 'atr_stop': 4, 'allowed_trend': ['flat', 'up'], 'fz_days': 30, 'fz_take': 2, 'take_atr': 1.0, 'short_allowed': ['flat'], 'btc_block_mode': 'both', 'fz_against': 1.5}

# a coin saját rezsimfeltétele + funding-felülbírálat a volbreak-h2026102801-v1 jele;
# erre jön utolsó lépésként a volbreak-h2026110202-v2 BTC-vezető tiltása
OVERRIDE = "volbreak-h2026102801-v1"
BTC = "BTCUSDT"


def _btc_gate(d, p, base, btc_trend):
    sig = base.loc[d.index]
    if d.index.get_level_values("symbol")[0] == BTC:
        return sig
    t = sig["target_position"]
    run = (t != t.shift()).cumsum()

    # a BTC (előző napi) címkéje a coin gyertyáira; BTC-gyertya hiányakor az utolsó ismert címke
    ts = d.index.get_level_values("ts")
    trend = pd.Series(btc_trend.reindex(ts, method="ffill").to_numpy(), index=d.index)

    # a döntés a szakasz elején születik; a felülbírálattal megnyitott kitörést is tiltja
    block_long = (trend == "down").groupby(run).transform("first")
    block_short = (trend == "up").groupby(run).transform("first") & (p["btc_block_mode"] == "both")
    out = lib.block_direction(sig, block_long, block_short)
    out.loc[((t > 0) & block_long) | ((t < 0) & block_short), "reason"] = ""
    return out


def signals(bars, regime, params):
    base_p = {k: v for k, v in params.items() if k != "btc_block_mode"}
    base = lib.parent_signals(OVERRIDE, bars, regime, base_p)
    has_btc = regime is not None and BTC in regime.index.get_level_values("symbol")
    btc_trend = regime.xs(BTC, level="symbol")["trend"].sort_index() if has_btc else pd.Series(dtype=object, index=pd.Index([], dtype="int64"))
    return lib.per_symbol(bars, lambda d, p, reg: _btc_gate(d, p, base, btc_trend), params)

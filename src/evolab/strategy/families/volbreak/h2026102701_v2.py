"""
family: volbreak
hypothesis_id: H-2026-10-27-01
parent_id: volbreak-h2026102601-v1
hypothesis: >
  Irányfüggő rezsimfeltétel. A szülő up-címke alatt a lefelé szűkülés-kitörésekbe is beszáll.
  Emelkedő trendben a lefelé kitörés jellemzően tőkeáttételes longok stopvadászata vagy rövid
  likvidációs kilengés. A mögöttes vételi kereslet (spot-beáramlás, dip-vásárlók) gyorsan
  visszaveszi a szintet, a késve beszálló short pedig a visszarántásnál veszít. Lefelé trendben
  fordított a helyzet: a lefelé kitörést a kapituláló longok és a csökkenő OI táplálják, ezért van
  követése. Ezért a long belépés feltétele változatlan (előző napi flat vagy up), a short belépés
  viszont csak a short_allowed címkék alatt nyílhat. A nyitott pozíciót, az ATR-trailinget és a
  funding-alapú profitrealizálást a feltétel nem érinti. A mozgással szemben álló oldal (trend
  elleni short) itt a vesztes.
expected_regimes: [up/low, up/mid, flat/low, flat/mid, down/mid]
falsifier: >
  Elvetjük, ha egyik változat sem éri el a PF 2x költségnél >= 1.3 értéket, vagy ha a PF 2x a
  szülőé (1.42) alá esik. Elvetjük akkor is, ha a szülő visszatesztjében az up-címke alatt nyitott
  shortok átlagos nettó hozama (2x költséggel) nem negatív: ekkor a kizárásuknak nincs mechanikus alapja.
"""


import pandas as pd

from evolab.strategy import lib

TIMEFRAME = "4h"
PARAMS = {'bb_n': 40, 'bb_k': 2.0, 'pct_window': 250, 'squeeze_pct': 20, 'squeeze_lookback': 6, 'atr_n': 14, 'atr_stop': 4, 'allowed_trend': ['flat', 'up'], 'fz_days': 30, 'fz_take': 2, 'take_atr': 1.0, 'short_allowed': ['flat', 'down']}

PARENT = "volbreak-h2026102601-v1"


def _short_gate(d, p, reg, parent):
    sig = parent.loc[d.index]
    t = sig["target_position"]
    run = (t != t.shift()).cumsum()

    # short csak ott nyílhat, ahol a belépő gyertya (előző napi) trendcímkéje engedett;
    # a döntés a szakasz elején születik, a nyitott pozíciót a címke későbbi váltása nem érinti
    short_ok = reg["trend"].isin(list(p["short_allowed"])) if reg is not None else pd.Series(False, index=d.index)
    short_ok = short_ok.reindex(d.index).fillna(False).astype(bool).groupby(run).transform("first")
    out = lib.block_direction(sig, pd.Series(False, index=d.index), ~short_ok)
    out.loc[(t < 0) & ~short_ok, "reason"] = ""
    return out


def signals(bars, regime, params):
    # a szülő (volbreak-h2026102601-v1) jele változatlanul
    parent_p = {k: v for k, v in params.items() if k != "short_allowed"}
    parent = lib.parent_signals(PARENT, bars, regime, parent_p)
    return lib.per_symbol(bars, lambda d, p, reg: _short_gate(d, p, reg, parent), params, regime)

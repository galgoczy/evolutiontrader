"""Diverzitás (docs/02-specifikacio.md 5.7). VÉDETT.

A populáció napi hozamainak korrelációs mátrixa. Ha két egyed korrelációja > `diversity.corr_max`,
a gyengébb DSR-ű a rangsorban büntetést kap (DSR × `diversity.dsr_penalty`). Ez megakadályozza,
hogy a populáció egy családra szűküljön. A büntetés csak a rangsort érinti, a ledger DSR-je nem változik.
Hozamsor: a paper napi hozama, ha legalább `MIN_PAPER_DAYS` nap van; addig a visszateszté.
"""

from __future__ import annotations

import pandas as pd

MIN_PAPER_DAYS = 20


def penalized_ranking(dsr: pd.Series, returns: pd.DataFrame, corr_max: float, penalty: float) -> pd.DataFrame:
    """`dsr`: egyed -> DSR; `returns`: nap × egyed. Visszaad: egyed, dsr, dsr_ranked, büntetve (kitől)."""
    ids = [i for i in dsr.index if i in returns.columns]
    corr = returns[ids].corr() if len(ids) > 1 else pd.DataFrame()
    adj = dsr.astype(float).copy()
    by = {i: [] for i in dsr.index}
    for a in ids:
        for b in ids:
            if a < b and corr.loc[a, b] > corr_max:
                weaker = a if dsr[a] < dsr[b] or (dsr[a] == dsr[b] and a > b) else b
                stronger = b if weaker == a else a
                by[weaker].append(stronger)
    for i, partners in by.items():
        if partners:
            adj[i] = dsr[i] * penalty  # egyszer büntet, akárhány hasonló párja van
    out = pd.DataFrame({"strategy_id": dsr.index, "dsr": dsr.values, "dsr_ranked": adj.values,
                        "penalized_by": [", ".join(by[i]) for i in dsr.index]})
    return out.sort_values(["dsr_ranked", "strategy_id"], ascending=[False, True]).reset_index(drop=True)


def correlation(returns: pd.DataFrame) -> pd.DataFrame:
    return returns.corr() if returns.shape[1] > 1 else pd.DataFrame()

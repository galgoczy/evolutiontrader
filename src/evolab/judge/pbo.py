"""A túlillesztés valószínűsége (PBO, Bailey–Borwein–López de Prado–Zhu). VÉDETT.

Bemenet: egy variáns-család napi hozammátrixa (nap × variáns), az azonos hipotézisből született
paraméter-variánsok (vagy a család összes variánsa, ha a hipotézisnek csak egy van).
Minden CPCV-kombinációban: a tanuló halmazon legjobb Sharpe-ú variáns relatív rangja a teszten
    ω = rang / (V + 1),   λ = ln(ω / (1 − ω)),
és PBO = a λ ≤ 0 kombinációk aránya (a tanulón legjobb a teszten a medián alatt vagy azon van).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import rankdata

from evolab.judge.cpcv import splits


def _sharpe_cols(m: np.ndarray) -> np.ndarray:
    sd = m.std(axis=0, ddof=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(sd > 0, m.mean(axis=0) / sd, 0.0)


def pbo(returns: pd.DataFrame, cfg_cpcv: dict) -> dict:
    """`returns`: napi hozam, index a nap (DatetimeIndex), oszlop a variáns. Legalább 2 variáns kell."""
    r = returns.sort_index().fillna(0.0)
    v = r.shape[1]
    if v < 2:
        return {"pbo": None, "variants": v, "combinations": 0, "reason": "2-nél kevesebb variáns"}
    m = r.to_numpy()
    logits = []
    for train, test in splits(r.index, cfg_cpcv["n_blocks"], cfg_cpcv["k_test"],
                              cfg_cpcv["purge_days"], cfg_cpcv["embargo_days"]):
        best = int(np.argmax(_sharpe_cols(m[train])))
        rank = rankdata(_sharpe_cols(m[test]))[best]  # 1 = legrosszabb, V = legjobb
        w = rank / (v + 1)
        logits.append(float(np.log(w / (1 - w))))
    lam = np.array(logits)
    return {"pbo": float((lam <= 0).mean()), "variants": v, "combinations": len(lam),
            "logit_median": float(np.median(lam))}

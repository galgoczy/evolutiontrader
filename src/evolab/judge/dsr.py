"""Deflated Sharpe Ratio (Bailey–López de Prado 2014, docs/02-specifikacio.md 5.4). VÉDETT.

Napi hozamokon, nem évesített Sharpe-pal (SR):
    SR0 = sqrt(V[SR]) * ((1 − γ) Φ⁻¹(1 − 1/N) + γ Φ⁻¹(1 − 1/(N e)))      (várt max. SR N kísérletből)
    DSR = Φ( (SR − SR0) √(T − 1) / √(1 − γ3 SR + (γ4 − 1)/4 SR²) )
γ = Euler–Mascheroni-állandó, γ3 ferdeség, γ4 csúcsosság (normális: 3), T megfigyelésszám.
N a kísérletek HATÉKONY száma: a kísérletek napi hozamainak korrelációs mátrixából
    N_eff = (Σλ)² / Σλ²     (λ: sajátértékek; teljesen korrelált -> 1, független -> N).
V[SR] a kísérletek SR-jeinek szórásnégyzete. Egyetlen kísérletnél SR0 = 0 (= valószínűségi Sharpe);
kis N-nél (≈1–2) a közelítés negatív SR0-t adna, ezért alulról 0-ra vágjuk.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy import stats

EULER_GAMMA = 0.5772156649015329


def sr(r: pd.Series | np.ndarray) -> float:
    r = np.asarray(r, dtype=float)
    sd = r.std(ddof=1) if len(r) > 1 else 0.0
    return float(r.mean() / sd) if sd > 0 else 0.0


def effective_trials(trials: pd.DataFrame) -> float:
    """Hatékony kísérletszám a napi hozamok korrelációjából (`trials`: nap × kísérlet)."""
    if trials.shape[1] <= 1:
        return float(trials.shape[1])
    c = trials.fillna(0.0).corr().fillna(0.0).to_numpy(copy=True)
    np.fill_diagonal(c, 1.0)
    lam = np.clip(np.linalg.eigvalsh(c), 0.0, None)
    return float(lam.sum() ** 2 / (lam ** 2).sum())


def expected_max_sr(sr_var: float, n: float) -> float:
    if n <= 1 or sr_var <= 0:
        return 0.0
    z = stats.norm.ppf
    e_max = math.sqrt(sr_var) * ((1 - EULER_GAMMA) * z(1 - 1 / n) + EULER_GAMMA * z(1 - 1 / (n * math.e)))
    return max(0.0, float(e_max))  # kis N-nél a közelítés negatív lenne; a null-hipotézis maximuma >= 0


def deflated_sharpe(returns: pd.Series, trials: pd.DataFrame | None = None) -> dict:
    """`returns`: a vizsgált variáns napi hozama. `trials`: a család kísérleteinek napi hozamai
    (nap × kísérlet), a vizsgált variánst is beleértve; None vagy 1 oszlop -> SR0 = 0."""
    r = pd.Series(returns).dropna()
    t = len(r)
    s = sr(r)
    if trials is not None and trials.shape[1] > 1:
        n_eff = effective_trials(trials)
        sr_var = float(np.var([sr(trials[c].dropna()) for c in trials.columns], ddof=1))
        n_raw = trials.shape[1]
    else:
        n_eff, sr_var, n_raw = 1.0, 0.0, 1 if trials is None else trials.shape[1]
    sr0 = expected_max_sr(sr_var, n_eff)
    g3 = float(stats.skew(r)) if t > 2 else 0.0
    g4 = float(stats.kurtosis(r, fisher=False)) if t > 3 else 3.0
    denom = 1 - g3 * s + (g4 - 1) / 4 * s ** 2
    z = (s - sr0) * math.sqrt(max(t - 1, 0)) / math.sqrt(denom) if denom > 0 and t > 1 else float("-inf")
    return {"dsr": float(stats.norm.cdf(z)), "sr": s, "sr0": sr0, "sr_var": sr_var, "n_trials": n_raw,
            "n_eff": n_eff, "t": t, "skew": g3, "kurtosis": g4}

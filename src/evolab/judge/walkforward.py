"""Walk-forward stabilitás (docs/02-specifikacio.md 5.2). VÉDETT.

Gördülő ablakok a holdout nélküli történelmen: `is_months` in-sample, utána `oos_months`
out-of-sample, `step_months` lépéssel. A paraméterek fixek (nincs ablakonkénti optimalizálás), így
az ablakozás egyetlen futás hozamsorán történik, és a stabilitást méri:
    OOS/IS arány = medián(OOS-Sharpe) / medián(IS-Sharpe).
Ha a medián IS-Sharpe nem pozitív, az arány 0 (nincs mit megtartani).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from evolab.judge.metrics import sharpe


def windows(start: pd.Timestamp, end: pd.Timestamp, is_m: int, oos_m: int, step_m: int):
    """(is_start, is_end, oos_end) hármasok; minden határ kizárólagos vég."""
    out = []
    s = start
    while True:
        is_end = s + pd.DateOffset(months=is_m)
        oos_end = is_end + pd.DateOffset(months=oos_m)
        if oos_end > end:
            return out
        out.append((s, is_end, oos_end))
        s = s + pd.DateOffset(months=step_m)


def evaluate(returns: pd.Series, periods_per_year: float, cfg_wf: dict) -> dict:
    """`returns`: gyertyahozam, index a gyertya zárási ideje (ms)."""
    if returns.empty:
        return {"windows": 0, "oos_is_ratio": 0.0, "is_sharpe_median": 0.0, "oos_sharpe_median": 0.0}
    idx = pd.to_datetime(returns.index, unit="ms", utc=True)
    r = pd.Series(returns.to_numpy(), index=idx)
    rows = []
    for a, b, c in windows(idx[0], idx[-1], cfg_wf["is_months"], cfg_wf["oos_months"], cfg_wf["step_months"]):
        rows.append({"is_start": a.strftime("%Y-%m-%d"), "oos_start": b.strftime("%Y-%m-%d"),
                     "is_sharpe": sharpe(r[(r.index > a) & (r.index <= b)], periods_per_year),
                     "oos_sharpe": sharpe(r[(r.index > b) & (r.index <= c)], periods_per_year)})
    if not rows:
        return {"windows": 0, "oos_is_ratio": 0.0, "is_sharpe_median": 0.0, "oos_sharpe_median": 0.0}
    is_med = float(np.median([x["is_sharpe"] for x in rows]))
    oos_med = float(np.median([x["oos_sharpe"] for x in rows]))
    return {"windows": len(rows), "is_sharpe_median": is_med, "oos_sharpe_median": oos_med,
            "oos_is_ratio": oos_med / is_med if is_med > 0 else 0.0, "detail": rows}

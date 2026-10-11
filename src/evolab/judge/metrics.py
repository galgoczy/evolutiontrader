"""Bírói mutatók (docs/02-specifikacio.md 5.1). VÉDETT: csak dátumozott, emberi jóváhagyással.

Minden mutató a szimulátor kimenetéből (`sim.engine.Result`) számolódik:
- gyertyahozam: a mark-equity változása gyertyáról gyertyára (évesítés √(gyertyák/év),
  4h-n √(6·365));
- napi hozam: a napi utolsó equity változása (DSR, CPCV, walk-forward alapja, idősíktól független).
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy import stats

from evolab.data.universe import tf_ms

YEAR_MS = 365 * 86_400_000


def bars_per_year(tf: str) -> float:
    return YEAR_MS / tf_ms(tf)


def bar_returns(equity: pd.DataFrame, initial: float) -> pd.Series:
    """Gyertyánkénti hozam; index a gyertya zárási ideje (ms)."""
    eq = pd.Series(equity["equity"].to_numpy(), index=equity["ts"].to_numpy())
    return eq.pct_change().fillna(eq.iloc[0] / initial - 1) if len(eq) else eq


def daily_returns(equity: pd.DataFrame, initial: float) -> pd.Series:
    """Napi hozam a nap utolsó equity-értékéből; index a nap (UTC, datetime)."""
    if equity.empty:
        return pd.Series(dtype=float)
    # a zárási idő 00:00 UTC-je az előző nap vége, ezért 1 ms-mal visszalépünk
    day = pd.to_datetime(equity["ts"].to_numpy() - 1, unit="ms", utc=True).normalize()
    eq = pd.Series(equity["equity"].to_numpy(), index=day).groupby(level=0).last()
    return eq.pct_change().fillna(eq.iloc[0] / initial - 1)


def sharpe(r: pd.Series, periods_per_year: float) -> float:
    sd = r.std(ddof=1)
    return float(r.mean() / sd * math.sqrt(periods_per_year)) if len(r) > 1 and sd > 0 else 0.0


def sortino(r: pd.Series, periods_per_year: float) -> float:
    downside = np.sqrt((np.minimum(r, 0.0) ** 2).mean())
    return float(r.mean() / downside * math.sqrt(periods_per_year)) if len(r) > 1 and downside > 0 else 0.0


def max_drawdown(equity: pd.Series) -> float:
    """Legnagyobb visszaesés (0..1) a mark-equity csúcsától."""
    return float((1 - equity / equity.cummax()).max()) if len(equity) else 0.0


def profit_factor(pnl: pd.Series) -> float:
    loss = -pnl[pnl < 0].sum()
    gain = pnl[pnl > 0].sum()
    if loss > 0:
        return float(gain / loss)
    return float("inf") if gain > 0 else 0.0


def regime_ev(trades: pd.DataFrame) -> dict[str, dict]:
    """Rezsimenkénti (trend×vol, a belépéskori címke) várható érték: kötésszám és átlagos PnL."""
    t = trades[trades["regime"].astype(str) != ""]
    out = {}
    for reg, g in t.groupby("regime"):
        out[str(reg)] = {"trades": int(len(g)), "ev": float(g["pnl"].mean())}
    return out


def compute(result, tf: str) -> dict:
    """A teljes mutatókészlet egy futásra (1x költség)."""
    eq_df = result.equity
    eq = eq_df["equity"]
    t = result.trades
    r = bar_returns(eq_df, result.initial_capital)
    rd = daily_returns(eq_df, result.initial_capital)
    ppy = bars_per_year(tf)
    years = (eq_df["ts"].iloc[-1] - eq_df["ts"].iloc[0] + tf_ms(tf)) / YEAR_MS if len(eq_df) else 0.0
    total = float(eq.iloc[-1] / result.initial_capital - 1) if len(eq) else 0.0
    cagr = (1 + total) ** (1 / years) - 1 if years > 0 and total > -1 else -1.0
    mdd = max_drawdown(pd.concat([pd.Series([result.initial_capital]), eq], ignore_index=True))
    hold_h = ((t["exit_ts"] - t["entry_ts"]) / 3_600_000).mean() if len(t) else 0.0
    traded = (t["qty"] * (t["entry_price"] + t["exit_price"])).sum() if len(t) else 0.0
    monthly = (1 + rd).groupby(rd.index.strftime("%Y-%m")).prod() - 1 if len(rd) else pd.Series(dtype=float)
    return {
        "trades": int(len(t)),
        "win_rate": float((t["pnl"] > 0).mean()) if len(t) else 0.0,
        "profit_factor": profit_factor(t["pnl"]) if len(t) else 0.0,
        "sharpe": sharpe(r, ppy),
        "sortino": sortino(r, ppy),
        "sharpe_daily_ann": sharpe(rd, 365),
        "total_return": total,
        "cagr": float(cagr),
        "max_dd": mdd,
        "calmar": float(cagr / mdd) if mdd > 0 else 0.0,
        "avg_hold_hours": float(hold_h),
        "turnover": float(traded / eq.mean() / years) if years > 0 and len(eq) else 0.0,
        "profitable_months": float((monthly > 0).mean()) if len(monthly) else 0.0,
        "skew": float(stats.skew(rd)) if len(rd) > 2 else 0.0,
        "kurtosis": float(stats.kurtosis(rd, fisher=False)) if len(rd) > 3 else 3.0,
        "fees": float(t["fees"].sum()) if len(t) else 0.0,
        "funding": float(t["funding"].sum()) if len(t) else 0.0,
        "years": float(years),
        "regime_ev": regime_ev(t),
        "status": result.status,
    }

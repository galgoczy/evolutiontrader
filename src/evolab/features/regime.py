"""Napi rezsimcímke coinonként: trend × vol × pozícionáltság (spec 2.4).

Időszemantika: a `date = D` címke a D napon NYÍLÓ napi gyertyából (zárás D+1 00:00 UTC), a D napi
funding-eseményekből és a D nap utolsó OI-értékéből számolódik. Egy stratégia gyertyájához ezért
mindig a gyertya napja ELŐTTI nap címkéje tartozik (lookahead-védelem, spec 3.).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from evolab.config import Config
from evolab.data import store
from evolab.data.universe import symbols
from evolab.db import connect, init_db
from evolab.features.indicators import adx, ema, realized_vol, rolling_percentile, zscore

DEFAULTS = {
    "adx_flat": 20,
    "vol_window": 30,
    "vol_lookback": 365,
    "vol_min_history": 180,
    "vol_low_pct": 33,
    "vol_high_pct": 67,
    "funding_z_window": 30,
    "funding_z_crowded": 1.5,
    "oi_change_days": 7,
}


def params(cfg: Config | None) -> dict:
    return {**DEFAULTS, **((cfg.lab.get("regime") or {}) if cfg else {})}


def label(daily: pd.DataFrame, funding: pd.DataFrame | None = None,
          metrics: pd.DataFrame | None = None, p: dict | None = None) -> pd.DataFrame:
    """Címkék egy coinra. `daily`: ts (ms), high, low, close napi gyertyák.

    Csak azok a napok kerülnek a kimenetbe, ahol a trend és a vol bemelegedett.
    Ha a funding még nem elég hosszú, a pozícionáltság `neutral`.
    """
    p = p or DEFAULTS
    d = daily.sort_values("ts").reset_index(drop=True)
    date = pd.to_datetime(d["ts"], unit="ms", utc=True).dt.normalize()

    # trend: close vs EMA50 és EMA200, ADX < küszöb -> flat
    c = d["close"]
    e50, e200, a = ema(c, 50), ema(c, 200), adx(d, 14)
    trend = np.select([(c > e50) & (c > e200), (c < e50) & (c < e200)], ["up", "down"], "flat")
    trend = pd.Series(trend, index=d.index).where(a >= p["adx_flat"], "flat")
    trend_ok = e200.notna() & a.notna()

    # vol: 30 napos realizált vol percentilise az elmúlt 365 naphoz képest
    pct = rolling_percentile(realized_vol(c, p["vol_window"]), p["vol_lookback"], p["vol_min_history"])
    vol = pd.Series(np.select([pct < p["vol_low_pct"], pct > p["vol_high_pct"]], ["low", "high"], "mid"),
                    index=d.index)

    # pozícionáltság: napi átlagos funding z-score-ja + OI 7 napos változása
    fz = pd.Series(np.nan, index=d.index)
    if funding is not None and not funding.empty:
        f = funding.assign(date=pd.to_datetime(funding["ts"], unit="ms", utc=True).dt.normalize())
        daily_f = f.groupby("date")["funding_rate"].mean()
        fz = date.map(zscore(daily_f, p["funding_z_window"]))
    oi_chg = pd.Series(np.nan, index=d.index)
    if metrics is not None and not metrics.empty:
        m = metrics.assign(date=pd.to_datetime(metrics["ts"], unit="ms", utc=True).dt.normalize())
        daily_oi = m.sort_values("ts").groupby("date")["oi"].last()
        daily_oi = daily_oi.asfreq("D")  # hiányzó nap ne csússzon el a 7 napos különbség
        oi_chg = date.map(daily_oi.pct_change(p["oi_change_days"], fill_method=None))
    oi_up = oi_chg.isna() | (oi_chg > 0)  # OI nélkül csak a funding dönt
    thr = p["funding_z_crowded"]
    pos = np.select([(fz > thr) & oi_up, (fz < -thr) & oi_up], ["crowded_long", "crowded_short"], "neutral")

    out = pd.DataFrame({"date": date.dt.strftime("%Y-%m-%d"), "trend": trend, "vol": vol,
                        "positioning": pos})
    return out[trend_ok & pct.notna()].reset_index(drop=True)


def compute(cfg: Config, symbol_list: list[str] | None = None) -> pd.DataFrame:
    frames = []
    p = params(cfg)
    for sym in symbol_list or symbols(cfg):
        daily = store.read_bars(cfg, sym, "1d")
        if daily.empty:
            continue
        lab = label(daily, store.read_funding(cfg, sym), store.read_metrics(cfg, sym), p)
        frames.append(lab.assign(symbol=sym))
    if not frames:
        return pd.DataFrame(columns=["date", "symbol", "trend", "vol", "positioning"])
    return pd.concat(frames, ignore_index=True)[["date", "symbol", "trend", "vol", "positioning"]]


def write(cfg: Config, df: pd.DataFrame) -> int:
    """A `regime_daily` tábla frissítése (felülírja az azonos (date, symbol) sorokat)."""
    init_db(cfg)
    with connect(cfg.db_path) as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO regime_daily(date, symbol, trend, vol, positioning) "
            "VALUES (?, ?, ?, ?, ?)",
            df[["date", "symbol", "trend", "vol", "positioning"]].itertuples(index=False, name=None),
        )
    return len(df)


def update(cfg: Config) -> int:
    return write(cfg, compute(cfg))

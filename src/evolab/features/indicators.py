"""Indikátorok. Mind kauzális: az i. érték csak az i. sorig látó adatból számolódik (spec 0.4)."""

from __future__ import annotations

import numpy as np
import pandas as pd


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def wilder(s: pd.Series, n: int) -> pd.Series:
    """Wilder-simítás (RMA), az ATR és az ADX alapja."""
    return s.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def true_range(df: pd.DataFrame) -> pd.Series:
    prev = df["close"].shift(1)
    return pd.concat(
        [df["high"] - df["low"], (df["high"] - prev).abs(), (df["low"] - prev).abs()], axis=1
    ).max(axis=1)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    return wilder(true_range(df), n)


def adx(df: pd.DataFrame, n: int = 14) -> pd.Series:
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)
    tr = wilder(true_range(df), n)
    plus_di = 100 * wilder(plus_dm, n) / tr
    minus_di = 100 * wilder(minus_dm, n) / tr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    return wilder(dx, n)


def bollinger(s: pd.Series, n: int = 20, k: float = 2.0) -> pd.DataFrame:
    mid = s.rolling(n).mean()
    sd = s.rolling(n).std(ddof=0)
    return pd.DataFrame({"mid": mid, "upper": mid + k * sd, "lower": mid - k * sd,
                         "width": 2 * k * sd / mid})


def realized_vol(close: pd.Series, n: int = 30, periods_per_year: int = 365) -> pd.Series:
    """Évesített realizált volatilitás log-hozamokból, n periódusos ablakon."""
    r = np.log(close).diff()
    return r.rolling(n).std() * np.sqrt(periods_per_year)


def rolling_percentile(s: pd.Series, window: int, min_periods: int) -> pd.Series:
    """Az aktuális érték percentilise (0..100) a saját múltbeli ablakában (az aktuálist is beleértve)."""
    def pct(w: np.ndarray) -> float:
        w = w[~np.isnan(w)]
        return 100.0 * (w <= w[-1]).mean()

    return s.rolling(window, min_periods=min_periods).apply(pct, raw=True).where(s.notna())


def zscore(s: pd.Series, n: int, min_periods: int | None = None) -> pd.Series:
    m = s.rolling(n, min_periods=min_periods or n)
    return (s - m.mean()) / m.std()

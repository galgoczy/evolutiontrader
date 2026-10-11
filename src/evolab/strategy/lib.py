"""Közös, kauzális jelépítő elemek a stratégiacsaládokhoz (spec 3.1).

Minden függvény egy coin idősorán (vagy coinpáron) dolgozik, és az i. sorban csak az i. sorig
látó adatot használja. A célpozíció-sorozat jelölése: +1 long, -1 short, 0 lapos.
Az „esemény + előrevitel” minta: egy állapotváltó esemény (+1 / -1 / 0) a saját gyertyáján
születik, és a következő eseményig érvényes (ffill), így a jel vektorizált marad.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from evolab.features.indicators import atr, bollinger, ema, zscore

DAY_MS = 86_400_000


def bars_per_day(d: pd.DataFrame) -> int:
    ts = d.index.get_level_values("ts")
    step = int(np.median(np.diff(ts))) if len(ts) > 1 else DAY_MS
    return max(1, DAY_MS // step)


def per_symbol(bars: pd.DataFrame, fn, params: dict, regime: pd.DataFrame | None = None) -> pd.DataFrame:
    """`fn(d, params, reg)` coinonként; a kimenet a bars indexére igazított SignalFrame."""
    out = []
    for sym, d in bars.groupby(level="symbol", sort=False):
        reg = regime.loc[d.index] if regime is not None and not regime.empty else None
        out.append(fn(d, params, reg))
    return pd.concat(out)


def hold(events: pd.Series) -> pd.Series:
    """Állapotváltó események (+1/-1/0, egyébként NaN) előrevitele; kezdetben lapos."""
    return events.ffill().fillna(0.0)


def trailing_stop(d: pd.DataFrame, target: pd.Series, n: int, k: float) -> pd.Series:
    """ATR-követő stop: egy-egy azonos irányú szakaszon belül csak a pozíció javára mozdul."""
    c, a = d["close"], atr(d, n)
    run = (target != target.shift()).cumsum()
    long_stop = (c - k * a).groupby(run).cummax()
    short_stop = (c + k * a).groupby(run).cummin()
    return long_stop.where(target > 0, short_stop.where(target < 0))


def frame(target: pd.Series, stop: pd.Series | None, long_reason: str, short_reason: str) -> pd.DataFrame:
    reason = pd.Series(np.select([target > 0, target < 0], [long_reason, short_reason], ""), index=target.index)
    return pd.DataFrame({"target_position": target.astype(float),
                         "stop_price": stop if stop is not None else np.nan, "reason": reason})


# ---------------------------------------------------------------- trend


def ema_cross(d: pd.DataFrame, fast: int, slow: int) -> pd.Series:
    f, s = ema(d["close"], fast), ema(d["close"], slow)
    return ((f > s).astype(float) - (f < s).astype(float)).where(s.notna(), 0.0)


def donchian(d: pd.DataFrame, n: int) -> pd.Series:
    """Fordító Donchian-kitörés: a megelőző n gyertya csúcsa fölötti zárás long, alja alatti short."""
    hi = d["high"].rolling(n).max().shift(1)
    lo = d["low"].rolling(n).min().shift(1)
    ev = pd.Series(np.select([d["close"] > hi, d["close"] < lo], [1.0, -1.0], np.nan), index=d.index)
    return hold(ev)


def tsmom(d: pd.DataFrame, lookback: int) -> pd.Series:
    """Idősoros momentum: a `lookback` gyertyás hozam előjele."""
    r = d["close"] / d["close"].shift(lookback) - 1
    return np.sign(r).fillna(0.0)


TREND_CORES = {"ema": lambda d, p: ema_cross(d, p["fast"], p["slow"]),
               "donchian": lambda d, p: donchian(d, p["n"]),
               "tsmom": lambda d, p: tsmom(d, p["lookback"])}


def trend_signal(d: pd.DataFrame, p: dict) -> pd.DataFrame:
    target = TREND_CORES[p["core"]](d, p)
    return frame(target, trailing_stop(d, target, p["atr_n"], p["atr_stop"]), f"{p['core']}_long", f"{p['core']}_short")


# ---------------------------------------------------------------- pozícionáltság


def funding_z(d: pd.DataFrame, days: int) -> pd.Series:
    """Az utolsó ismert funding-ráta z-score-ja a `days` napos múltjához képest."""
    last = d["funding_rate"].where(d["funding_rate"] != 0).ffill()
    return zscore(last, days * bars_per_day(d), min_periods=max(10, days * bars_per_day(d) // 2))


def oi_change(d: pd.DataFrame, days: int) -> pd.Series:
    if "oi" not in d:
        return pd.Series(np.nan, index=d.index)
    return d["oi"].ffill().pct_change(days * bars_per_day(d), fill_method=None)


def crowding(d: pd.DataFrame, p: dict) -> pd.Series:
    """+1 zsúfolt long (magas funding-z, növő OI), -1 zsúfolt short, 0 semleges.
    OI-adat nélkül csak a funding dönt."""
    z = funding_z(d, p["fz_days"])
    oi = oi_change(d, p["oi_days"])
    oi_up = oi.isna() | (oi > 0)
    return pd.Series(np.select([(z > p["fz_thr"]) & oi_up, (z < -p["fz_thr"]) & oi_up], [1.0, -1.0], 0.0),
                     index=d.index)


def filtered_trend_signal(d: pd.DataFrame, p: dict) -> pd.DataFrame:
    """Trendjel, de zsúfolt irányba nem lép be (és onnan kiszáll)."""
    target = TREND_CORES[p["core"]](d, p)
    crowd = crowding(d, p)
    target = target.where(~(((target > 0) & (crowd > 0)) | ((target < 0) & (crowd < 0))), 0.0)
    return frame(target, trailing_stop(d, target, p["atr_n"], p["atr_stop"]),
                 f"{p['core']}_long_unfiltered", f"{p['core']}_short_unfiltered")


def contrarian_signal(d: pd.DataFrame, p: dict) -> pd.DataFrame:
    """Zsúfolt pozícionáltság ellen: zsúfolt long -> short, zsúfolt short -> long; |z| < exit -> ki."""
    z = funding_z(d, p["fz_days"])
    crowd = crowding(d, p)
    ev = pd.Series(np.select([crowd > 0, crowd < 0, z.abs() < p["fz_exit"]], [-1.0, 1.0, 0.0], np.nan),
                   index=d.index)
    target = hold(ev)
    return frame(target, trailing_stop(d, target, p["atr_n"], p["atr_stop"]), "fade_crowded_short", "fade_crowded_long")


# ---------------------------------------------------------------- volatilitás-kitörés


def squeeze_breakout_signal(d: pd.DataFrame, p: dict) -> pd.DataFrame:
    """Bollinger-szűkülés (sávszélesség-percentilis < küszöb az elmúlt `pct_window` gyertyán) utáni
    kitörés a sávon kívülre; kilépés a középvonal visszakeresztezésekor vagy ATR-stoppal."""
    bb = bollinger(d["close"], p["bb_n"], p["bb_k"])
    w = bb["width"]
    pct = w.rolling(p["pct_window"], min_periods=p["pct_window"] // 2).rank(pct=True) * 100
    squeezed = (pct < p["squeeze_pct"]).astype(float).rolling(p["squeeze_lookback"], min_periods=1).max().shift(1) > 0
    c = d["close"]
    side = np.sign(c - bb["mid"])
    cross_mid = side != side.shift()
    ev = pd.Series(np.select([squeezed & (c > bb["upper"]), squeezed & (c < bb["lower"]), cross_mid],
                             [1.0, -1.0, 0.0], np.nan), index=d.index)
    target = hold(ev)
    return frame(target, trailing_stop(d, target, p["atr_n"], p["atr_stop"]), "squeeze_break_up", "squeeze_break_down")


# ---------------------------------------------------------------- tartományvisszatérés


def range_reversion_signal(d: pd.DataFrame, p: dict, reg: pd.DataFrame | None) -> pd.DataFrame:
    """Bollinger-visszatérés, csak `trend = flat` címke alatt (az előző nap címkéje): alsó sáv alatt
    long, felső fölött short, a középvonalnál ki; nem-flat napon azonnal ki."""
    bb = bollinger(d["close"], p["bb_n"], p["bb_k"])
    c = d["close"]
    flat = (reg["trend"] == "flat") if reg is not None else pd.Series(False, index=d.index)
    side = np.sign(c - bb["mid"])
    cross_mid = side != side.shift()
    ev = pd.Series(np.select([~flat, c < bb["lower"], c > bb["upper"], cross_mid], [0.0, 1.0, -1.0, 0.0], np.nan),
                   index=d.index)
    target = hold(ev)
    return frame(target, trailing_stop(d, target, p["atr_n"], p["atr_stop"]), "bb_revert_long", "bb_revert_short")


# ---------------------------------------------------------------- relatív erő


def pair_reversion_signal(bars: pd.DataFrame, p: dict) -> pd.DataFrame:
    """Két coin log-árarányának z-score-ja: z > belépő -> A short, B long; z < -belépő -> fordítva;
    |z| < kilépő -> mindkét láb ki. A többi coin lapos. Ha valamelyik coin hiányzik, minden lapos."""
    a, b = p["leg_a"], p["leg_b"]
    out = pd.DataFrame({"target_position": 0.0, "stop_price": np.nan, "reason": ""}, index=bars.index)
    syms = set(bars.index.get_level_values("symbol"))
    if a not in syms or b not in syms:
        return out
    ca, cb = bars.loc[a, "close"], bars.loc[b, "close"]
    common = ca.index.intersection(cb.index)
    ratio = np.log(ca.loc[common] / cb.loc[common])
    z = zscore(ratio, p["z_window"])
    ev = pd.Series(np.select([z > p["z_entry"], z < -p["z_entry"], z.abs() < p["z_exit"]], [-1.0, 1.0, 0.0], np.nan),
                   index=common)
    leg = hold(ev)  # +1: A long, B short
    for sym, sign in ((a, 1.0), (b, -1.0)):
        idx = pd.MultiIndex.from_arrays([[sym] * len(common), common], names=["symbol", "ts"])
        t = (sign * leg).to_numpy()
        out.loc[idx, "target_position"] = t
        out.loc[idx, "reason"] = np.select([t > 0, t < 0], [f"{a}/{b}_z_long", f"{a}/{b}_z_short"], "")
    return out

"""Parquet-tár: útvonalak, atomi írás, olvasás, hiánykeresés (docs/02-specifikacio.md 2.2).

Elrendezés a data/ alatt:
  raw/binance/...                        letöltött, checksummal ellenőrzött zipek (gyorsítótár)
  binance/<symbol>/<tf>.parquet          ts, open, high, low, close, volume, quote_volume, trades,
                                         mark_close, premium_close
  binance/<symbol>/funding.parquet       ts, funding_rate, funding_interval_hours
  binance/<symbol>/metrics.parquet       ts, oi, oi_value (5 perces open interest)
  hl/<symbol>/ticks_<YYYY-MM-DD>.parquet élő rögzítő percenként
  hl/<symbol>/candles_<tf>.parquet       Hyperliquid lezárt gyertyák
  hl/<symbol>/funding.parquet            Hyperliquid óránkénti funding
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

import pandas as pd

from evolab.config import Config
from evolab.data.universe import tf_ms

BAR_COLUMNS = [
    "ts", "open", "high", "low", "close", "volume", "quote_volume", "trades",
    "mark_close", "premium_close",
]


def data_dir(cfg: Config) -> Path:
    return cfg.path("data")


def raw_dir(cfg: Config) -> Path:
    return data_dir(cfg) / "raw" / "binance"


def bars_path(cfg: Config, symbol: str, tf: str) -> Path:
    return data_dir(cfg) / "binance" / symbol / f"{tf}.parquet"


def funding_path(cfg: Config, symbol: str) -> Path:
    return data_dir(cfg) / "binance" / symbol / "funding.parquet"


def metrics_path(cfg: Config, symbol: str) -> Path:
    return data_dir(cfg) / "binance" / symbol / "metrics.parquet"


def hl_dir(cfg: Config, symbol: str) -> Path:
    return data_dir(cfg) / "hl" / symbol


def write_parquet(df: pd.DataFrame, path: Path) -> None:
    """Atomi írás: ideiglenes fájlba, majd átnevezés (félbeszakadt írás nem ront el semmit)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)


# ---------------------------------------------------------------- holdout-izoláció (spec 9.)
# A bíró az in-sample értékelést `holdout_locked(cut)` alatt futtatja: ilyenkor a tár egyetlen
# olvasója sem ad vissza a `cut` utáni időbélyeget, és egy kifejezetten oda mutató kérés hibát dob.
_HOLDOUT_CUT_MS: int | None = None


class HoldoutViolation(PermissionError):
    pass


@contextmanager
def holdout_locked(cut_ms: int):
    global _HOLDOUT_CUT_MS
    prev = _HOLDOUT_CUT_MS
    _HOLDOUT_CUT_MS = int(cut_ms) if prev is None else min(prev, int(cut_ms))  # egymásba ágyazva a szigorúbb
    try:
        yield
    finally:
        _HOLDOUT_CUT_MS = prev


def holdout_cut_ms() -> int | None:
    return _HOLDOUT_CUT_MS


def _guard(df: pd.DataFrame) -> pd.DataFrame:
    if _HOLDOUT_CUT_MS is None or df.empty or "ts" not in df:
        return df
    return df[df["ts"] < _HOLDOUT_CUT_MS].reset_index(drop=True)


def read_parquet(path: Path) -> pd.DataFrame:
    return _guard(pd.read_parquet(path)) if path.exists() else pd.DataFrame()


def read_bars(cfg: Config, symbol: str, tf: str) -> pd.DataFrame:
    return read_parquet(bars_path(cfg, symbol, tf))


def read_funding(cfg: Config, symbol: str) -> pd.DataFrame:
    return read_parquet(funding_path(cfg, symbol))


def read_metrics(cfg: Config, symbol: str) -> pd.DataFrame:
    return read_parquet(metrics_path(cfg, symbol))


def missing_bars(ts: pd.Series, tf: str) -> pd.DatetimeIndex:
    """A hiányzó gyertyák nyitó ideje az első és az utolsó gyertya között."""
    if ts.empty:
        return pd.DatetimeIndex([], tz="UTC")
    step = tf_ms(tf)
    have = pd.Index(ts.astype("int64"))
    grid = pd.RangeIndex(int(have.min()), int(have.max()) + step, step)
    gaps = grid.difference(have)
    return pd.to_datetime(gaps, unit="ms", utc=True)


def funding_by_bar(funding: pd.DataFrame, tf: str) -> pd.Series:
    """Funding-események a gyertyához rendelve, amelyiknek a ZÁRÁSA az esemény ideje.

    Az esemény `f` időpontja (a Binance néhány ms késéssel írja, ezért mp-re kerekítve) a
    (nyitó, zárás] intervallumba eső gyertyához tartozik: így a ráta a gyertya zárásakor ismert,
    és a szimulátor az akkor tartott pozícióra számolja el.
    """
    if funding.empty:
        return pd.Series(dtype=float)
    step = tf_ms(tf)
    f = (funding["ts"].astype("int64") + 500) // 1000 * 1000
    bar = (f - 1) // step * step
    return funding["funding_rate"].groupby(bar.values).sum()


def load_barframe(cfg: Config, symbols: list[str], tf: str, end_ms: int | None = None) -> pd.DataFrame:
    """BarFrame (spec 3.): (symbol, ts) multi-index, OHLCV + mark_close + funding_rate.

    `end_ms`: csak az ennél korábban NYÍLÓ gyertyák (holdout-vágás). A `funding_rate` a gyertya
    alatt esedékes funding-események összege (0, ha nincs esemény).
    """
    if _HOLDOUT_CUT_MS is not None and end_ms is not None and end_ms > _HOLDOUT_CUT_MS:
        raise HoldoutViolation(f"a holdout-ablak ({_HOLDOUT_CUT_MS} ms-tól) zárolva, kért vég: {end_ms}")
    frames = []
    for sym in symbols:
        df = read_bars(cfg, sym, tf)
        if df.empty:
            continue
        if end_ms is not None:
            df = df[df["ts"] < end_ms]
        fr = funding_by_bar(read_funding(cfg, sym), tf)
        df = df.assign(funding_rate=df["ts"].map(fr).fillna(0.0).astype(float), symbol=sym)
        frames.append(df)
    if not frames:
        raise FileNotFoundError(f"Nincs {tf} gyertya a {symbols} coinokra (evolab data update).")
    out = pd.concat(frames, ignore_index=True)
    return out.set_index(["symbol", "ts"]).sort_index()

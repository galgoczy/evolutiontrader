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


def read_parquet(path: Path) -> pd.DataFrame:
    return pd.read_parquet(path) if path.exists() else pd.DataFrame()


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

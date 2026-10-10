"""Univerzum, idősíkok és időkezelés (docs/02-specifikacio.md 2.1)."""

from __future__ import annotations

import datetime as dt

import pandas as pd

from evolab.config import Config

TF_MS = {"1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}


def symbols(cfg: Config) -> list[str]:
    return list(cfg.lab["universe"])


def timeframes(cfg: Config) -> list[str]:
    return list(cfg.lab["timeframes"])


def history_start(cfg: Config) -> pd.Timestamp:
    return pd.Timestamp(cfg.lab["history_start"], tz="UTC")


def hl_coin(symbol: str) -> str:
    """Binance-szimbólum -> Hyperliquid coin-név (BTCUSDT -> BTC)."""
    return symbol.removesuffix("USDT")


def tf_ms(tf: str) -> int:
    return TF_MS[tf]


def now_ms() -> int:
    return int(dt.datetime.now(dt.UTC).timestamp() * 1000)


def last_closed_open_ms(tf: str, now: int | None = None) -> int:
    """Az utolsó LEZÁRT gyertya nyitó ideje (ms). A még nyitott gyertya sosem kerül be."""
    step = tf_ms(tf)
    now = now_ms() if now is None else now
    return (now // step) * step - step


def to_ms(values: pd.Series) -> pd.Series:
    """Időbélyeg normalizálása ms-re: a Binance 2025-től helyenként mikroszekundumot ad."""
    v = pd.to_numeric(values).astype("int64")
    return v.where(v < 10**14, v // 1000)

"""Stratégiasablon (docs/02-specifikacio.md 3.): az egyetlen felület, amit a fejlesztő LLM kitölt.

Egy stratégiafájl (`strategy/families/<család>/<variáns>.py`) tartalma:
- modul-docstring = YAML fejléc: `family`, `hypothesis` (min. 200 karakter), `expected_regimes`,
  `falsifier`;
- `TIMEFRAME` ("4h" vagy "1h"), `PARAMS` (dict);
- `signals(bars, regime, params) -> SignalFrame`: vektorizált, a teljes idősorra egyszerre.

Időszemantika (lookahead-védelem):
- `bars`: BarFrame, (symbol, ts) multi-index, `ts` a gyertya NYITÓ ideje (UTC ms).
- A jel a gyertya ZÁRÁSÁN születik (csak a saját gyertyájáig látó adatból), és a szimulátor a
  KÖVETKEZŐ gyertya nyitóján teljesíti.
- `regime`: a gyertyához az ELŐZŐ nap napi címkéje tartozik (`align_regime`).

A sablonban nincs kockázatkezelés: méretezés, tőkeáttét, megszakítók a `sim/risk.py`-ban.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Protocol

import pandas as pd

BarFrame = pd.DataFrame  # (symbol, ts) index; open, high, low, close, volume, ..., mark_close, funding_rate
RegimeFrame = pd.DataFrame  # (symbol, ts) index; trend, vol, positioning (az előző nap címkéje)
SignalFrame = pd.DataFrame  # (symbol, ts) index; target_position, stop_price, take_profit_price, reason

SIGNAL_COLUMNS = ["target_position", "stop_price", "take_profit_price", "reason"]
REGIME_COLUMNS = ["trend", "vol", "positioning"]
DAY_MS = 86_400_000


@dataclass(frozen=True)
class StrategyMeta:
    id: str
    family: str
    timeframe: str
    params: dict[str, Any]
    parent_id: str | None = None
    hypothesis_id: str | None = None
    created_at: str = field(default_factory=lambda: dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
    header: dict[str, Any] = field(default_factory=dict)  # a fájl YAML fejléce


class Strategy(Protocol):
    meta: StrategyMeta

    def signals(self, bars: BarFrame, regime: RegimeFrame) -> SignalFrame: ...


def align_regime(regime_daily: pd.DataFrame, index: pd.MultiIndex) -> RegimeFrame:
    """Napi címkék a gyertyákhoz igazítva: a D napon nyíló gyertya a D-1 napi címkét kapja.

    A D-1 címke a D-1 napon nyíló napi gyertyából számolódik, ami D 00:00 UTC-kor zár, így a D
    napi gyertyák idején már ismert. Címke nélküli gyertyánál (bemelegedés) az érték NaN.
    """
    frame = index.to_frame(index=False)
    prev_day = (frame["ts"] // DAY_MS - 1) * DAY_MS
    frame["date"] = pd.to_datetime(prev_day, unit="ms", utc=True).dt.strftime("%Y-%m-%d")
    lab = regime_daily[["date", "symbol", *REGIME_COLUMNS]] if not regime_daily.empty else \
        pd.DataFrame(columns=["date", "symbol", *REGIME_COLUMNS])
    out = frame.merge(lab, on=["symbol", "date"], how="left")
    return out.set_index(["symbol", "ts"])[REGIME_COLUMNS]


def validate_signals(sig: pd.DataFrame, bars: BarFrame) -> SignalFrame:
    """Kiegészíti és ellenőrzi a stratégia kimenetét; hibás kimenetnél ValueError."""
    sig = sig.copy()
    if "target_position" not in sig:
        raise ValueError("a SignalFrame-ből hiányzik a target_position oszlop")
    for col, default in (("stop_price", float("nan")), ("take_profit_price", float("nan")), ("reason", "")):
        if col not in sig:
            sig[col] = default
    sig = sig[SIGNAL_COLUMNS].reindex(bars.index)
    tp = sig["target_position"].fillna(0.0).astype(float)
    if (tp.abs() > 1.0 + 1e-12).any():
        raise ValueError("target_position a [-1, 1] tartományon kívül")
    sig["target_position"] = tp
    sig["reason"] = sig["reason"].fillna("").astype(str)
    return sig

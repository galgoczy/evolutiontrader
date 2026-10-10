"""Spec 0.4 és 9.: egy jövőbeli gyertya módosítása nem változtathat múltbeli jelet és rezsimcímkét."""

import numpy as np
import pandas as pd
import pytest

from evolab.features import indicators as ind
from evolab.features import regime

DAY = 86_400_000
T0 = int(pd.Timestamp("2021-01-01", tz="UTC").timestamp() * 1000)
N = 700


def _synthetic(seed: int = 1):
    rng = np.random.default_rng(seed)
    # rezsimváltó ár: emelkedő, oldalazó, eső szakaszok, változó vol-lal
    drift = np.repeat([0.004, 0.0, -0.004, 0.002], N // 4 + 1)[:N]
    vol = np.repeat([0.02, 0.04, 0.015, 0.05], N // 4 + 1)[:N]
    close = 100 * np.exp(np.cumsum(drift + vol * rng.standard_normal(N)))
    ts = T0 + DAY * np.arange(N)
    daily = pd.DataFrame({"ts": ts, "open": close, "high": close * 1.01, "low": close * 0.99, "close": close})
    fts = T0 + 8 * 3_600_000 * np.arange(N * 3)
    funding = pd.DataFrame({"ts": fts, "funding_rate": 1e-4 + 2e-4 * rng.standard_normal(N * 3)})
    mts = T0 + 3_600_000 * np.arange(N * 24)
    metrics = pd.DataFrame({"ts": mts, "oi": 1e6 * np.exp(np.cumsum(0.002 * rng.standard_normal(N * 24)))})
    return daily, funding, metrics


def _future_shock(daily, funding, metrics, cut_ms):
    """Minden `cut_ms` utáni adat durva megváltoztatása."""
    d, f, m = daily.copy(), funding.copy(), metrics.copy()
    fut = d["ts"] >= cut_ms
    d.loc[fut, ["open", "high", "low", "close"]] *= 3.0
    d.loc[fut, "high"] *= 1.5
    f.loc[f["ts"] >= cut_ms, "funding_rate"] = 0.01
    m.loc[m["ts"] >= cut_ms, "oi"] *= 10
    return d, f, m


@pytest.mark.parametrize("cut_day", [450, 600, N - 1])
def test_regime_labels_ignore_future(cut_day):
    daily, funding, metrics = _synthetic()
    base = regime.label(daily, funding, metrics)
    cut_ms = T0 + cut_day * DAY
    shocked = regime.label(*_future_shock(daily, funding, metrics, cut_ms))
    cut_date = pd.Timestamp(cut_ms, unit="ms", tz="UTC").strftime("%Y-%m-%d")
    past_a = base[base["date"] < cut_date].reset_index(drop=True)
    past_b = shocked[shocked["date"] < cut_date].reset_index(drop=True)
    assert len(past_a) > 100
    pd.testing.assert_frame_equal(past_a, past_b)
    # a sokk valóban hat a jövőre (különben a teszt semmit nem bizonyítana)
    if cut_day < N - 1:
        assert not base[base["date"] >= cut_date].reset_index(drop=True).equals(
            shocked[shocked["date"] >= cut_date].reset_index(drop=True))


def test_regime_labels_ignore_appended_bar():
    """Új gyertya hozzáadása (a napi futás esete) nem írja át a régi címkéket."""
    daily, funding, metrics = _synthetic()
    a = regime.label(daily.iloc[:-1], funding, metrics)
    b = regime.label(daily, funding, metrics)
    pd.testing.assert_frame_equal(a, b.iloc[: len(a)])


def test_regime_uses_all_axes():
    daily, funding, metrics = _synthetic()
    lab = regime.label(daily, funding, metrics)
    assert set(lab["trend"]) == {"up", "down", "flat"}
    assert set(lab["vol"]) == {"low", "mid", "high"}
    assert lab["positioning"].nunique() >= 2


@pytest.mark.parametrize("fn", [
    lambda d: ind.ema(d["close"], 50),
    lambda d: ind.atr(d, 14),
    lambda d: ind.adx(d, 14),
    lambda d: ind.bollinger(d["close"])["width"],
    lambda d: ind.realized_vol(d["close"], 30),
    lambda d: ind.rolling_percentile(ind.realized_vol(d["close"], 30), 365, 180),
])
def test_indicators_ignore_future(fn):
    daily, _, _ = _synthetic()
    cut = 500
    shocked, _, _ = _future_shock(daily, daily[["ts"]].assign(funding_rate=0.0),
                                  daily[["ts"]].assign(oi=1.0), T0 + cut * DAY)
    pd.testing.assert_series_equal(fn(daily).iloc[:cut], fn(shocked).iloc[:cut])


@pytest.mark.xfail(reason="stratégiajel a 2. fázisban készül (strategy/base.py)", strict=True)
def test_strategy_signals_ignore_future():
    from evolab.strategy import base  # noqa: F401

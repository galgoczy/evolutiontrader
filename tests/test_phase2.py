"""2. fázis: stratégiasablon, registry, szimulátor (költség, funding, stop, megszakítók), visszateszt."""

import json
import textwrap

import numpy as np
import pandas as pd
import pytest

from evolab import backtest
from evolab.data import store
from evolab.db import connect
from evolab.sim import engine
from evolab.sim.costs import Costs
from evolab.sim.funding import payment
from evolab.sim.risk import Breakers, RiskParams, vol_target_weight
from evolab.strategy import registry
from evolab.strategy.base import align_regime

H4 = 4 * 3_600_000
DAY = 86_400_000
T0 = int(pd.Timestamp("2022-01-01", tz="UTC").timestamp() * 1000)
NO_BREAKERS = RiskParams(0.01, 2.0, 0.5, consecutive_losses=99, daily_dd_pct=100, weekly_dd_pct=100)


def make_bars(symbols=("BTCUSDT", "ETHUSDT"), n=900, seed=7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    frames = []
    for k, sym in enumerate(symbols):
        drift = np.repeat([0.003, -0.002, 0.0, 0.004], n // 4 + 1)[:n]
        close = 100 * (k + 1) * np.exp(np.cumsum(drift + 0.02 * rng.standard_normal(n)))
        open_ = np.concatenate([[close[0]], close[:-1]])
        ts = T0 + H4 * np.arange(n)
        frames.append(pd.DataFrame({
            "symbol": sym, "ts": ts, "open": open_, "high": np.maximum(open_, close) * 1.005,
            "low": np.minimum(open_, close) * 0.995, "close": close, "volume": 1.0, "quote_volume": 1.0,
            "trades": 1, "mark_close": close, "premium_close": 0.0,
            "funding_rate": np.where(ts % (8 * 3_600_000) == 0, 1e-4, 0.0),
        }))
    return pd.concat(frames).set_index(["symbol", "ts"]).sort_index()


def frame_from_opens(opens, targets, stops=None, tps=None, funding=None):
    """Egy coin, 4h: a záró = a következő nyitó; high/low a nyitó és záró körül 0,5-tel."""
    o = np.array(opens, dtype=float)
    c = np.append(o[1:], o[-1])
    n = len(o)
    idx = pd.MultiIndex.from_arrays([["BTCUSDT"] * n, T0 + H4 * np.arange(n)], names=["symbol", "ts"])
    bars = pd.DataFrame({"open": o, "high": np.maximum(o, c) + 0.5, "low": np.minimum(o, c) - 0.5, "close": c,
                         "mark_close": c, "funding_rate": funding if funding is not None else np.zeros(n)},
                        index=idx)
    sig = pd.DataFrame({"target_position": np.array(targets, dtype=float),
                        "stop_price": np.nan if stops is None else np.array(stops, dtype=float),
                        "take_profit_price": np.nan if tps is None else np.array(tps, dtype=float),
                        "reason": "teszt"}, index=idx)
    return bars, sig


def notional_1000(sym, target, vol, equity):
    """Teszt-méretező: minden kötés 1000 USD névértékű, így a kötések függetlenek."""
    return np.sign(target) * 1000.0 / equity


# ---------------------------------------------------------------- szimulátor


def test_sim_known_answer():
    """Kézzel számolt 5 kötés: taker 0,1%, slippage 0,05%, funding három gyertyán."""
    opens = [100, 100, 102, 104, 103, 101, 99, 100, 103, 105, 104, 102, 100, 100]
    targets = [1, 1, 0, -1, -1, 1, 1, 0, 1, 0, -1, 0, 0, 0]
    funding = np.zeros(len(opens))
    funding[1], funding[4], funding[7] = 0.0001, 0.0002, -0.0001
    bars, sig = frame_from_opens(opens, targets, funding=funding)
    costs = Costs(taker_fee=0.001, slippage_base=0.0005, slippage_atr_mult=0.0)
    res = engine.run(bars, sig, "4h", costs, NO_BREAKERS, sizer=notional_1000)

    fee, slip = 0.001, 0.0005

    def trade(side, entry_open, exit_open, funding_bars):
        entry = entry_open * (1 + side * slip)
        qty = 1000.0 / entry
        exit_ = exit_open * (1 - side * slip)
        fund = sum(-side * qty * close * rate for close, rate in funding_bars)
        return side * qty * (exit_ - entry) - fee * 1000.0 - fee * qty * exit_ + fund

    # (oldal, belépő nyitó, kilépő nyitó, [(mark-záró, ráta) a tartás alatti funding-gyertyákra])
    expected = [
        trade(+1, 100, 104, [(102, 0.0001)]),   # 1. gyertya nyitóján be, 3. nyitóján ki
        trade(-1, 103, 99, [(101, 0.0002)]),    # short: 4. be, 6. ki (fordulás)
        trade(+1, 99, 103, [(103, -0.0001)]),   # 6. be (fordulás), 8. ki; negatív ráta: a long kap
        trade(+1, 105, 104, []),                # 9. be, 10. ki
        trade(-1, 102, 100, []),                # 11. be, 12. ki
    ]
    t = res.trades
    assert len(t) == 5
    assert t["side"].tolist() == [1, -1, 1, 1, -1]
    assert t["entry_ts"].tolist() == [T0 + H4 * k for k in (1, 4, 6, 9, 11)]
    np.testing.assert_allclose(t["pnl"].to_numpy(), expected, rtol=1e-12)
    np.testing.assert_allclose(res.equity["equity"].iloc[-1], 10_000 + sum(expected), rtol=1e-12)
    assert t["exit_reason"].tolist() == ["signal"] * 5


def test_sim_deterministic():
    strat = registry.load("trend-ema-cross-4h-01")
    bars = make_bars()
    costs = Costs(0.00045, 0.0002, 0.05)
    hashes = set()
    for _ in range(2):
        sig = strat.signals(bars, align_regime(pd.DataFrame(), bars.index))
        res = engine.run(bars, sig, "4h", costs, NO_BREAKERS)
        hashes.add(res.trades_hash())
    assert len(res.trades) > 5
    assert len(hashes) == 1


def test_sim_stop_wins_over_take_profit_and_blocks_reentry():
    opens = [100, 100, 100, 100, 100, 100]
    targets = [1, 1, 1, 1, 1, 0]
    bars, sig = frame_from_opens(opens, targets, stops=[95] * 6, tps=[105] * 6)
    bars.loc[bars.index[2], ["high", "low"]] = [106, 94]  # a 2. gyertyában mindkettő érintett
    res = engine.run(bars, sig, "4h", Costs(0.0, 0.0, 0.0), NO_BREAKERS, sizer=notional_1000)
    t = res.trades
    assert len(t) == 1  # a stop után a célérték (1) nem változott -> nincs visszalépés
    assert t["exit_reason"].iloc[0] == "stop"
    assert t["exit_price"].iloc[0] == 95
    assert t["exit_ts"].iloc[0] == T0 + 2 * H4


def test_sim_gap_through_stop_fills_at_open():
    opens = [100, 100, 100, 90, 90]
    bars, sig = frame_from_opens(opens, [1, 1, 1, 1, 0], stops=[95] * 5)
    bars.loc[bars.index[2], ["close", "low", "mark_close"]] = [99, 98.5, 99]  # éjszakai rés 99 -> 90
    res = engine.run(bars, sig, "4h", Costs(0.0, 0.0, 0.0), NO_BREAKERS, sizer=notional_1000)
    assert res.trades["exit_price"].iloc[0] == 90  # a nyitó már a stop alatt volt
    assert res.trades["exit_ts"].iloc[0] == T0 + 3 * H4


def test_sim_gross_leverage_cap():
    bars = make_bars(n=10)
    sig = pd.DataFrame({"target_position": 1.0, "reason": "x"}, index=bars.index)
    sig["stop_price"] = np.nan
    sig["take_profit_price"] = np.nan
    res = engine.run(bars, sig, "4h", Costs(0.0, 0.0, 0.0), NO_BREAKERS,
                     sizer=lambda s, t, v, e: 1.5)  # coinonként 1,5x -> a 2x bruttó plafon levág
    assert res.equity["gross_exposure"].max() <= 2.0 + 0.1  # árváltozás miatt kicsit elmozdulhat
    assert res.trades["qty"].iloc[1] * res.trades["entry_price"].iloc[1] == pytest.approx(5_000, rel=1e-9)


def test_funding_sign():
    assert payment(+2.0, 100.0, 0.001) == pytest.approx(-0.2)  # long fizet
    assert payment(-2.0, 100.0, 0.001) == pytest.approx(0.2)   # short kap


def test_funding_by_bar_maps_to_closing_bar():
    f = pd.DataFrame({"ts": [T0 + 8 * 3_600_000 + 18, T0 + 16 * 3_600_000], "funding_rate": [0.1, 0.2]})
    by_bar = store.funding_by_bar(f, "4h")
    # a 08:00:00.018-as esemény a 04:00-kor nyíló (08:00-kor záró) gyertyához tartozik
    assert by_bar.to_dict() == {T0 + H4: 0.1, T0 + 3 * H4: 0.2}


# ---------------------------------------------------------------- kockázat


def test_vol_target_weight_portfolio_budget():
    p = RiskParams(0.01, 2.0, 0.5, 3, 5, 10)
    assert vol_target_weight(1.0, 0.02, p, n_coins=5) == pytest.approx(0.1)   # 0,01/5 / 0,02
    assert vol_target_weight(-0.5, 0.02, p, n_coins=5) == pytest.approx(-0.05)
    assert vol_target_weight(1.0, 0.001, p, n_coins=1) == 0.5                 # coin-plafon
    assert vol_target_weight(1.0, float("nan"), p, n_coins=5) == 0.0


def test_breaker_consecutive_losses_pause():
    b = Breakers(RiskParams(0.01, 2.0, 0.5, 3, 5, 10))
    for k in range(3):
        b.on_trade_closed(T0 + k, -1.0)
    assert b.paused(T0 + 3) and not b.paused(T0 + 2 + DAY)
    b2 = Breakers(RiskParams(0.01, 2.0, 0.5, 3, 5, 10))
    for k, pnl in enumerate([-1, -1, 1, -1]):
        b2.on_trade_closed(T0 + k, pnl)
    assert not b2.paused(T0 + 4)


def test_breaker_daily_and_weekly_drawdown():
    b = Breakers(RiskParams(0.01, 2.0, 0.5, 3, 5, 10))
    b.on_equity(T0, 100.0)
    b.on_equity(T0 + H4, 94.0)  # -6% egy napon belül
    assert b.paused(T0 + H4 + 1) and b.failed_at is None
    for d, eq in enumerate([93.0, 92.0, 91.0, 89.0], start=1):
        b.on_equity(T0 + d * DAY, eq)
    assert b.failed_at == T0 + 4 * DAY  # -11% a 7 napos csúcstól


def test_weekly_drawdown_stops_run():
    opens = [100, 100, 100, 80, 80, 80, 80]
    bars, sig = frame_from_opens(opens, [1] * 7)
    risk = RiskParams(0.01, 2.0, 0.5, 99, 100, 10)
    res = engine.run(bars, sig, "4h", Costs(0.0, 0.0, 0.0), risk, sizer=lambda s, t, v, e: 1.0)
    assert res.status == "failed"
    assert res.trades["exit_reason"].tolist() == ["breaker_failed"]
    assert res.equity["ts"].iloc[-1] < T0 + 7 * H4  # a futás a vége előtt leállt


# ---------------------------------------------------------------- sablon, registry, rezsim


def test_align_regime_uses_previous_day():
    idx = pd.MultiIndex.from_arrays([["BTCUSDT"] * 3, [T0 + DAY, T0 + DAY + 20 * 3_600_000, T0 + 2 * DAY]],
                                    names=["symbol", "ts"])
    lab = pd.DataFrame({"date": ["2022-01-01", "2022-01-02"], "symbol": "BTCUSDT", "trend": ["up", "down"],
                        "vol": ["low", "high"], "positioning": "neutral"})
    out = align_regime(lab, idx)
    assert out["trend"].tolist() == ["up", "up", "down"]  # 01-02 gyertyái a 01-01 címkéjét kapják


def _write_strategy(root, family, name, hypothesis):
    d = root / family
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.py").write_text(textwrap.dedent(f'''\
        """
        family: {family}
        hypothesis: "{hypothesis}"
        expected_regimes: [up/high]
        falsifier: "ha nem működik"
        """
        TIMEFRAME = "4h"
        PARAMS = {{"k": 1}}

        def signals(bars, regime, params):
            import pandas as pd
            return pd.DataFrame({{"target_position": 0.0}}, index=bars.index)
        '''), encoding="utf-8")


def test_registry_rejects_short_hypothesis(tmp_path):
    _write_strategy(tmp_path, "trend", "short_01", "túl rövid")
    with pytest.raises(registry.StrategyRejected, match="legalább 200"):
        registry.load("trend-short-01", tmp_path)


def test_registry_rejects_family_mismatch(tmp_path):
    _write_strategy(tmp_path, "volbreak", "y_01", "a" * 250)
    (tmp_path / "trend").mkdir()
    (tmp_path / "volbreak" / "y_01.py").rename(tmp_path / "trend" / "y_01.py")  # rossz mappába
    with pytest.raises(registry.StrategyRejected, match="nem egyezik"):
        registry.load("trend-y-01", tmp_path)


def test_registry_loads_first_trend_variant():
    s = registry.load("trend-ema-cross-4h-01")
    assert s.meta.family == "trend" and s.meta.timeframe == "4h"
    assert len(s.meta.header["hypothesis"]) >= 200
    sig = s.signals(make_bars(n=300), align_regime(pd.DataFrame(), make_bars(n=300).index))
    assert set(sig["target_position"].unique()) <= {-1.0, 0.0, 1.0}
    held = sig[sig["target_position"] != 0]
    assert held["stop_price"].notna().all()


# ---------------------------------------------------------------- visszateszt-futtató


def test_backtest_writes_outputs_and_ledger(cfg):
    bars = make_bars(symbols=cfg.lab["universe"], n=3000)  # ~16 hónap
    for sym, df in bars.groupby(level="symbol"):
        df = df.reset_index()
        store.write_parquet(df.drop(columns=["symbol", "funding_rate"]), store.bars_path(cfg, sym, "4h"))
        f = df.loc[df["funding_rate"] != 0, ["ts", "funding_rate"]]
        store.write_parquet(f.assign(funding_interval_hours=8), store.funding_path(cfg, sym))
    last = pd.Timestamp(int(bars.index.get_level_values("ts").max()), unit="ms", tz="UTC")
    today = (last - pd.DateOffset(months=1)).date()  # holdout: today előtti 6 hónap levágva
    bt = backtest.run(cfg, "trend-ema-cross-4h-01", today=today)
    cut_ms = int(bt.holdout_start.timestamp() * 1000)
    for name in ("trades", "equity", "exposure", "events"):
        assert (bt.out_dir / f"{name}.parquet").exists()
    eq = pd.read_parquet(bt.out_dir / "equity.parquet")
    assert eq["ts"].max() <= cut_ms  # a holdout-ablakból semmi
    with connect(cfg.db_path) as conn:
        row = conn.execute("SELECT * FROM trials WHERE trial_id = ?", (bt.trial_id,)).fetchone()
        strat = conn.execute("SELECT * FROM strategies WHERE strategy_id = 'trend-ema-cross-4h-01'").fetchone()
    assert row["judge_version"] == cfg.judge_version and row["holdout_used"] == 0
    m = json.loads(row["is_metrics_json"])
    assert m["trades"] == len(bt.result.trades) and m["trades_hash"] == bt.result.trades_hash()
    assert strat["file_path"].endswith("ema_cross_4h_01.py")
    # ugyanaz az adat -> ugyanaz a kötéslista (determinizmus a teljes láncon)
    assert backtest.run(cfg, "trend-ema-cross-4h-01", today=today, write=False).result.trades_hash() == \
        bt.result.trades_hash()


def test_weekly_drawdown_on_last_bar_marks_failed():
    bars, sig = frame_from_opens([100, 100, 100], [1] * 3)
    bars.loc[bars.index[-1], ["close", "low", "mark_close"]] = [80, 79.5, 80]  # esés az utolsó gyertyán
    res = engine.run(bars, sig, "4h", Costs(0.0, 0.0, 0.0), RiskParams(0.01, 2.0, 0.5, 99, 100, 10),
                     sizer=lambda s, t, v, e: 1.0)
    assert res.status == "failed"
    assert res.trades["exit_reason"].tolist() == ["breaker_failed"]

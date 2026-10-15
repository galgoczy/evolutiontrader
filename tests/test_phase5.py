"""5. fázis: élő paper (Hyperliquid BarFrame, újrajátszás, névsor), paper = visszateszt, riport, dashboard."""

import json

import numpy as np
import pandas as pd
import pytest

from evolab.data import store
from evolab.db import connect, init_db
from evolab.judge import ledger
from evolab.live import paper_runner as pr
from evolab.report import daily, dashboard
from evolab.sim import engine
from evolab.sim.costs import Costs
from evolab.sim.risk import RiskParams
from test_phase3 import H4, T0, write_env

DAY = 86_400_000
SID = "trend-ema-cross-4h-01"


def write_hl_from_binance(cfg, noise: float = 0.0, seed: int = 0):
    """A szintetikus Binance-sorból Hyperliquid-gyertya és -funding (opcionális árzajjal)."""
    rng = np.random.default_rng(seed)
    for sym in cfg.lab["universe"]:
        b = store.read_bars(cfg, sym, "4h")
        k = 1 + noise * rng.standard_normal(len(b))
        c = b[["ts", "open", "high", "low", "close", "volume", "trades"]].copy()
        for col in ("open", "high", "low", "close"):
            c[col] = c[col] * k
        store.write_parquet(c, store.hl_dir(cfg, sym) / "candles_4h.parquet")
        f = store.read_funding(cfg, sym)[["ts", "funding_rate"]].assign(premium=0.0)
        store.write_parquet(f, store.hl_dir(cfg, sym) / "funding.parquet")


def paper_env(cfg, noise=0.0, days=30):
    write_env(cfg, n=3000, symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"))
    write_hl_from_binance(cfg, noise)
    end = int(store.read_bars(cfg, "BTCUSDT", "4h")["ts"].max()) + H4
    start = end - days * DAY
    pr.write_roster(cfg, {"strategies": {SID: {"mode": "shadow", "start_ms": start, "added": "teszt"}}})
    return start, end


@pytest.mark.parametrize("noise", [0.0, 0.0005])
def test_paper_equals_backtest(cfg, noise):
    """Ugyanarra a 30 napra a paper (Hyperliquid-sor) és a visszateszt (Binance-sor) equity-je ±5%-on belül;
    azonos adaton pontosan egyezik (egy kód, két mód)."""
    paper_env(cfg, noise=noise)
    c = pr.compare(cfg, SID)
    assert c["days"] == pytest.approx(30.0) and c["final_check"]
    assert c["ok"] and c["diff_pct"] <= 5.0
    if noise == 0.0:
        assert c["diff_pct"] == pytest.approx(0.0, abs=1e-9) and c["paper_trades"] == c["backtest_trades"]


def test_paper_run_writes_outputs_and_keeps_open_positions(cfg):
    start, end = paper_env(cfg)
    out = pr.run(cfg, sync=False, log=lambda *_: None)
    s = out[SID]
    assert "error" not in s and s["bars"] == 30 * 6 and s["last_bar_close"] == end
    eq = pd.read_parquet(pr.paper_dir(cfg) / SID / "equity.parquet")
    assert eq["ts"].min() == start + H4  # az első lezárt gyertya a kezdet után
    trades = pd.read_parquet(pr.paper_dir(cfg) / SID / "trades.parquet")
    assert (trades["mode"] == "paper").all() and not (trades["exit_reason"] == "end").any()
    with connect(cfg.db_path) as conn:
        assert conn.execute("SELECT status FROM runs WHERE kind = 'paper'").fetchone()["status"] == "ok"


def test_paper_replay_is_consistent_with_incremental(cfg):
    """Az újrajátszás egy rövidebb (korábbi) adatsoron ugyanazt adja a közös részre: amit ma könyvelt,
    holnap sem írja át."""
    start, end = paper_env(cfg)
    bars, regime = pr._inputs(cfg, "4h", "hl", {})
    full = pr.simulate(cfg, SID, start, bars, regime)
    cut = end - 10 * DAY
    keep = bars.index.get_level_values("ts") < cut
    part = pr.simulate(cfg, SID, start, bars[keep], regime[keep])
    pd.testing.assert_frame_equal(part.equity, full.equity.iloc[: len(part.equity)].reset_index(drop=True))
    closed = full.trades[full.trades["exit_ts"] <= cut - H4]
    pd.testing.assert_frame_equal(part.trades, closed.reset_index(drop=True))


def test_stop_file_skips_paper(cfg):
    paper_env(cfg)
    cfg.stop_file.write_text("")
    assert pr.run(cfg, sync=False, log=lambda *_: None) == {}


def test_engine_keeps_open_positions_when_asked():
    idx = pd.MultiIndex.from_arrays([["BTCUSDT"] * 4, T0 + H4 * np.arange(4)], names=["symbol", "ts"])
    bars = pd.DataFrame({"open": 100.0, "high": 101.0, "low": 99.0, "close": [100.0, 100, 100, 110],
                         "mark_close": [100.0, 100, 100, 110], "funding_rate": 0.0}, index=idx)
    sig = pd.DataFrame({"target_position": 1.0, "stop_price": np.nan, "take_profit_price": np.nan, "reason": "x"},
                       index=idx)
    res = engine.run(bars, sig, "4h", Costs(0, 0, 0), RiskParams(0.01, 2, 0.5, 99, 100, 100),
                     sizer=lambda *a: 0.5, close_at_end=False)
    assert res.trades.empty and len(res.open_positions) == 1
    assert res.equity["equity"].iloc[-1] == pytest.approx(10_000 + 50 * 10)  # 5000 USD / 100 = 50 db, +10


# ---------------------------------------------------------------- Hyperliquid BarFrame


def test_hl_barframe_uses_mid_at_open_and_marks_before_close(cfg):
    sym = "BTCUSDT"
    candles = pd.DataFrame({"ts": T0 + H4 * np.arange(2), "open": [100.0, 102], "high": 105.0, "low": 95.0,
                            "close": [102.0, 103], "volume": 1.0, "trades": 1})
    store.write_parquet(candles, store.hl_dir(cfg, sym) / "candles_4h.parquet")
    ticks = pd.DataFrame({"ts": [T0, T0 + H4 - 60_000, T0 + H4, T0 + H4 + 60_000],
                          "mark_px": [100.1, 101.9, 102.2, 102.5], "mid_px": [100.05, 101.95, 102.15, 102.4],
                          "open_interest": [5.0, 6.0, 7.0, 8.0]})
    store.write_parquet(ticks, store.hl_dir(cfg, sym) / f"ticks_{pd.Timestamp(T0, unit='ms'):%Y-%m-%d}.parquet")
    store.write_parquet(pd.DataFrame({"ts": [T0 + 3_600_000 + 5, T0 + 2 * 3_600_000], "funding_rate": [1e-5, 2e-5],
                                      "premium": 0.0}), store.hl_dir(cfg, sym) / "funding.parquet")
    b = store.load_hl_barframe(cfg, [sym], "4h").loc[sym]
    assert b["open"].tolist() == [100.05, 102.15]          # a nyitó perc mid ára
    assert b["mark_close"].iloc[0] == 101.9                # a zárás előtti utolsó mark, nem a záráskori
    assert b["oi"].iloc[0] == 6.0 and b["oi"].iloc[1] == 8.0
    assert b["funding_rate"].iloc[0] == pytest.approx(3e-5)


def test_measured_slippage_from_impact_prices(cfg):
    sym = "BTCUSDT"
    now = T0 + DAY
    t = pd.DataFrame({"ts": now - 60_000 * np.arange(1, 11), "mark_px": 100.0, "mid_px": 100.0,
                      "open_interest": 1.0, "impact_bid": 99.98, "impact_ask": 100.02})
    store.write_parquet(t, store.hl_dir(cfg, sym) / "ticks_x.parquet")
    s = pr.measured_slippage(cfg, days=7, now=now).set_index("symbol")
    assert s.loc[sym, "samples"] == 10 and s.loc[sym, "measured_pct"] == pytest.approx(0.02)
    assert s.loc["ETHUSDT", "samples"] == 0


# ---------------------------------------------------------------- névsor


def _verdict(cfg, sid, dsr):
    ledger.record(cfg, {"trial_id": f"t-{sid}", "strategy_id": sid, "family": sid.split("-")[0],
                        "params_hash": "p", "data_hash": "d", "dsr": dsr, "pbo": 0.1, "gate_result": "fail",
                        "is_metrics_json": json.dumps({"trades": 1, "profit_factor": 1.0, "pf_2x": 1.0,
                                                       "max_dd": 0.1, "regime_ev": {}}),
                        "wf_metrics_json": json.dumps({}), "gate_failures": json.dumps([])})


def test_roster_shadow_top_n_frozen_and_l2_added(cfg):
    cfg.lab["paper"]["shadow_top_n"] = 2
    _verdict(cfg, "trend-ema-cross-4h-01", 0.5)
    _verdict(cfg, "trend-ema-cross-4h-02", 0.9)
    _verdict(cfg, "volbreak-squeeze-4h-04", 0.7)
    r = pr.ensure_roster(cfg, now=T0)
    assert {k: v["mode"] for k, v in r["strategies"].items()} == {
        "trend-ema-cross-4h-02": "shadow", "volbreak-squeeze-4h-04": "shadow"}
    _verdict(cfg, "trend-donchian-4h-01", 0.99)            # később jobb DSR jön...
    assert set(pr.ensure_roster(cfg, now=T0 + DAY)["strategies"]) == set(r["strategies"])  # ...a lista nem változik
    init_db(cfg)
    with connect(cfg.db_path) as conn:
        conn.execute("INSERT INTO strategies(strategy_id, family, timeframe, file_path, level) "
                     "VALUES ('trend-ema-cross-4h-01', 'trend', '4h', 'x', 'L2')")
    r2 = pr.ensure_roster(cfg, now=T0 + 2 * DAY)
    assert r2["strategies"]["trend-ema-cross-4h-01"]["mode"] == "L2"
    assert r2["strategies"]["trend-ema-cross-4h-01"]["start_ms"] == (T0 + 2 * DAY) // H4 * H4
    new = pr.ensure_roster(cfg, now=T0 + 3 * DAY, reselect_shadow=True)["strategies"]
    assert "trend-donchian-4h-01" in new and new["trend-ema-cross-4h-01"]["mode"] == "L2"


# ---------------------------------------------------------------- riport, dashboard


def test_daily_report_and_dashboard_write(cfg):
    paper_env(cfg)
    pr.run(cfg, sync=False, log=lambda *_: None)
    _verdict(cfg, SID, 0.6)
    r = daily.build(cfg)
    md, js = daily.write(cfg, r)
    text = md.read_text(encoding="utf-8")
    for heading in ("## Populáció (L1)", "## Élő paper", "## Slippage", "## Kísérletszám", "## Rögzítő"):
        assert heading in text
    assert json.loads(js.read_text(encoding="utf-8"))["paper"][0]["strategy_id"] == SID
    page = dashboard.write(cfg, r).read_text(encoding="utf-8")
    assert "<svg" in page and SID in page and "prefers-color-scheme:dark" in page
    assert "L1: 0/1 átment" in daily.telegram_text(r)
    assert r["awaiting_approval"] == []  # a várólista a létra L1 szintje, nem az L1-ítéletek listája

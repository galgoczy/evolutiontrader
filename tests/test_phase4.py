"""4. fázis: induló populáció (40 variáns), közös jelépítők, OI a BarFrame-ben, riport."""

import json
from collections import Counter

import numpy as np
import pandas as pd

from evolab.data import store
from evolab.evolve import population
from evolab.judge import ledger
from evolab.strategy import lib, registry

H4 = 4 * 3_600_000
T0 = int(pd.Timestamp("2023-01-01", tz="UTC").timestamp() * 1000)


def _one(close, symbol="BTCUSDT", **extra):
    close = np.asarray(close, dtype=float)
    o = np.concatenate([[close[0]], close[:-1]])
    idx = pd.MultiIndex.from_arrays([[symbol] * len(close), T0 + H4 * np.arange(len(close))],
                                    names=["symbol", "ts"])
    return pd.DataFrame({"open": o, "high": np.maximum(o, close), "low": np.minimum(o, close), "close": close,
                         "funding_rate": 0.0, **extra}, index=idx)


def test_population_matches_families_config(cfg):
    loaded = [registry.load_file(p) for p in registry.discover().values()]
    loaded = [s for s in loaded if (s.meta.hypothesis_id or "").startswith("H-seed")]  # az induló populáció
    counts = Counter(s.meta.family for s in loaded)
    assert dict(counts) == {f: c["initial_variants"] for f, c in cfg.families["families"].items()}
    assert sum(counts.values()) == cfg.lab["population"]["initial"] == 40
    hyps = Counter(s.meta.hypothesis_id for s in loaded)
    assert None not in hyps and min(hyps.values()) >= 2  # a PBO-hoz minden hipotézisnek legalább 2 variánsa van
    for s in loaded:  # a családok idősíkja a families.yaml szerint
        assert s.meta.timeframe in cfg.families["families"][s.meta.family]["timeframes"]


def test_donchian_reverses_on_opposite_breakout():
    close = [10] * 5 + [12, 12, 12] + [7, 7]
    t = lib.donchian(_one(close), 3)
    assert t.tolist()[:5] == [0.0] * 5 and t.iloc[5] == 1.0 and t.iloc[7] == 1.0 and t.iloc[8] == -1.0


def test_pair_reversion_opposite_legs_others_flat():
    rng = np.random.default_rng(0)
    n = 400
    btc = 100 * np.exp(np.cumsum(0.01 * rng.standard_normal(n)))
    eth = btc * np.exp(np.concatenate([np.zeros(300), np.full(100, 0.3)]))  # ETH/BTC hirtelen elszakad
    bars = pd.concat([_one(btc, "BTCUSDT"), _one(eth, "ETHUSDT"), _one(btc, "SOLUSDT")])
    sig = lib.pair_reversion_signal(bars, {"leg_a": "ETHUSDT", "leg_b": "BTCUSDT", "z_window": 60,
                                           "z_entry": 2.0, "z_exit": 0.5})
    e, b = sig.loc["ETHUSDT", "target_position"], sig.loc["BTCUSDT", "target_position"]
    assert (e == -b).all() and e.iloc[301] == -1.0  # elszakadás után: ETH short, BTC long
    assert (sig.loc["SOLUSDT", "target_position"] == 0).all()


def test_range_reversion_only_in_flat_regime():
    close = 100 + 5 * np.sin(np.arange(300) / 5)
    d = _one(close)
    params = {"bb_n": 20, "bb_k": 1.5, "atr_n": 14, "atr_stop": 2.0}
    up = pd.DataFrame({"trend": "up"}, index=d.index)
    flat = pd.DataFrame({"trend": "flat"}, index=d.index)
    assert (lib.range_reversion_signal(d, params, up)["target_position"] == 0).all()
    assert (lib.range_reversion_signal(d, params, flat)["target_position"] != 0).any()


def test_positioning_filter_blocks_crowded_direction():
    n = 600
    close = 100 * np.exp(np.linspace(0, 1, n))  # tiszta emelkedés: a trendjel végig long
    ts = T0 + H4 * np.arange(n)
    funding = np.where(ts % (8 * 3_600_000) == 0, 1e-4, 0.0)
    funding[(ts % (8 * 3_600_000) == 0) & (np.arange(n) > 400)] = 5e-3  # a végén szélsőséges funding
    d = _one(close, funding_rate=funding, oi=np.linspace(1, 2, n))
    d["funding_rate"] = funding
    p = {"core": "ema", "fast": 10, "slow": 50, "fz_days": 30, "fz_thr": 1.5, "oi_days": 7, "atr_n": 14,
         "atr_stop": 3.0}
    raw = lib.trend_signal(d, p)["target_position"]
    filt = lib.filtered_trend_signal(d, p)["target_position"]
    assert raw.iloc[410] == 1.0 and filt.iloc[410] == 0.0  # zsúfolt long: nem lépünk be
    assert (filt.iloc[100:400] == raw.iloc[100:400]).all()


def test_barframe_oi_known_at_bar_close(cfg):
    sym = "BTCUSDT"
    bars = pd.DataFrame({"ts": T0 + H4 * np.arange(3), "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0,
                         "volume": 1.0, "quote_volume": 1.0, "trades": 1, "mark_close": 1.0, "premium_close": 0.0})
    store.write_parquet(bars, store.bars_path(cfg, sym, "4h"))
    # OI pontosan a 0. gyertya zárásakor (= az 1. nyitása) és egy perccel utána
    store.write_parquet(pd.DataFrame({"ts": [T0 + H4, T0 + H4 + 60_000], "oi": [10.0, 20.0], "oi_value": 0.0}),
                        store.metrics_path(cfg, sym))
    oi = store.load_barframe(cfg, [sym], "4h")["oi"].tolist()
    assert oi[0] == 10.0                      # a 0. gyertya zárásakor ismert érték (a későbbi 20 nem)
    assert oi[1] == 20.0 and np.isnan(oi[2])  # a 2. gyertyához egy gyertyán belül nincs friss adat


def test_population_report_latest_verdict_per_strategy(cfg):
    def row(tid, sid, fam, result):
        m = {"trades": 120, "profit_factor": 1.4, "pf_2x": 1.3, "max_dd": 0.1,
             "regime_ev": {"up/high": {"trades": 3, "ev": 1.0}, "down/high": {"trades": 30, "ev": 2.0}}}
        return {"trial_id": tid, "strategy_id": sid, "family": fam, "params_hash": "p", "data_hash": "d",
                "is_metrics_json": json.dumps(m), "wf_metrics_json": json.dumps({"oos_is_ratio": 0.7}),
                "dsr": 0.9, "pbo": 0.1, "gate_result": result, "gate_failures": json.dumps([])}
    for r in (row("a1", "trend-x", "trend", "fail"), row("a2", "trend-x", "trend", "pass"),
              row("b1", "volbreak-y", "volbreak", "fail"), {**row("c1", "trend-x", "trend", None),
                                                            "gate_result": "stability_probe"}):
        ledger.record(cfg, r)
    table, fam = population.report(cfg)
    assert table.set_index("strategy_id").loc["trend-x", "result"] == "pass"  # a legutolsó ítélet számít
    assert fam.set_index("family").loc["trend", "passed"] == 1
    row = table.set_index("strategy_id").loc["trend-x"]
    assert row["regimes_pos"] == 1 and row["regimes_pos_any"] == 2  # a 3 kötéses (< 5) a kapunál nem számít
    assert "| strategy_id |" in population.md_table(table)

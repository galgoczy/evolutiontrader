"""3. fázis: bíró (mutatók, walk-forward, CPCV, PBO, DSR, ledger, kapuk, holdout-izoláció)."""

import datetime as dt
import json
import math
import re

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from evolab import backtest
from evolab.data import store
from evolab.db import connect
from evolab.features import regime as regime_mod
from evolab.judge import cpcv, dsr, gates, holdout, ledger, pbo, walkforward
from evolab.judge.evaluate import evaluate_l1, perturbations
from evolab.judge.metrics import daily_returns
from evolab.sim import engine
from evolab.sim.costs import Costs
from evolab.sim.risk import RiskParams
from evolab.strategy import registry
from evolab.strategy.base import align_regime

H4 = 4 * 3_600_000
DAY = 86_400_000
T0 = int(pd.Timestamp("2021-01-01", tz="UTC").timestamp() * 1000)
EMA_FILE = registry.FAMILIES_DIR / "trend" / "ema_cross_4h_01.py"


# ---------------------------------------------------------------- szintetikus környezet


def synth_bars(n: int, seed: int, trend: bool) -> pd.DataFrame:
    """4h gyertyák; `trend`: 90 napos, váltakozó irányú erős trendek, különben véletlen bolyongás."""
    rng = np.random.default_rng(seed)
    drift = np.where((np.arange(n) // 540) % 2 == 0, 0.0015, -0.0012) if trend else np.zeros(n)
    close = 100 * np.exp(np.cumsum(drift + 0.008 * rng.standard_normal(n)))
    o = np.concatenate([[close[0]], close[:-1]])
    return pd.DataFrame({"ts": T0 + H4 * np.arange(n), "open": o, "high": np.maximum(o, close) * 1.002,
                         "low": np.minimum(o, close) * 0.998, "close": close, "volume": 1.0,
                         "quote_volume": 1.0, "trades": 1, "mark_close": close, "premium_close": 0.0})


def write_env(cfg, n=8760, trend=True, symbols=("BTCUSDT", "ETHUSDT")):
    """Szintetikus 4h + 1d gyertya, funding és rezsimcímke a tesztkonfigba."""
    cfg.lab["universe"] = list(symbols)
    for k, sym in enumerate(symbols):
        df = synth_bars(n, seed=11 + k, trend=trend)
        store.write_parquet(df, store.bars_path(cfg, sym, "4h"))
        day = df.assign(d=df["ts"] // DAY * DAY).groupby("d").agg(
            open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"),
            volume=("volume", "sum"), quote_volume=("quote_volume", "sum"), trades=("trades", "sum"),
            mark_close=("mark_close", "last"), premium_close=("premium_close", "last")).reset_index()
        store.write_parquet(day.rename(columns={"d": "ts"})[store.BAR_COLUMNS], store.bars_path(cfg, sym, "1d"))
        fts = df["ts"][df["ts"] % (8 * 3_600_000) == 0]
        store.write_parquet(pd.DataFrame({"ts": fts, "funding_rate": 5e-5, "funding_interval_hours": 8}),
                            store.funding_path(cfg, sym))
    regime_mod.update(cfg)
    last = pd.Timestamp(T0 + H4 * n, unit="ms", tz="UTC")
    return (last + pd.DateOffset(months=1)).date()  # "ma": a holdout az utolsó 5 hónapot vágja le


def write_variants(root, params_list):
    """EMA-kereszt variánsok egy ideiglenes `families/trend` mappába."""
    src = EMA_FILE.read_text(encoding="utf-8")
    (root / "trend").mkdir(parents=True, exist_ok=True)
    ids = []
    for k, p in enumerate(params_list, start=1):
        text = re.sub(r"^PARAMS = .*$", f"PARAMS = {p!r}", src, flags=re.M)
        (root / "trend" / f"ema_cross_4h_{k:02d}.py").write_text(text, encoding="utf-8")
        ids.append(f"trend-ema-cross-4h-{k:02d}")
    return ids


# ---------------------------------------------------------------- DSR


def test_dsr_single_trial_is_probabilistic_sharpe():
    rng = np.random.default_rng(0)
    r = pd.Series(0.001 + 0.01 * rng.standard_normal(1000))
    out = dsr.deflated_sharpe(r)
    s = r.mean() / r.std(ddof=1)
    g3, g4 = stats.skew(r), stats.kurtosis(r, fisher=False)
    expected = stats.norm.cdf(s * math.sqrt(999) / math.sqrt(1 - g3 * s + (g4 - 1) / 4 * s * s))
    assert out["sr0"] == 0 and out["dsr"] == pytest.approx(expected)


def test_expected_max_sr_grows_with_trials():
    vals = [dsr.expected_max_sr(0.01, n) for n in (1, 2, 10, 100, 1000)]
    assert vals[0] == 0 and all(a <= b for a, b in zip(vals, vals[1:])) and vals[-1] > 0.25


def test_effective_trials_from_correlation():
    rng = np.random.default_rng(1)
    base = rng.standard_normal(500)
    same = pd.DataFrame({f"c{k}": base for k in range(10)})
    indep = pd.DataFrame({f"c{k}": rng.standard_normal(500) for k in range(10)})
    assert dsr.effective_trials(same) == pytest.approx(1.0)
    assert 8.0 < dsr.effective_trials(indep) <= 10.0


def test_judge_rejects_overfit():
    """Él nélküli adaton (6 coin véletlen bolyongása, 3 év) 100 véletlen paraméterű EMA-kereszt
    legjobbikának DSR-je < 0,95, miközben a naiv (egyetlen kísérletnek tekintett) Sharpe-próba
    átengedné. Más sorsolásokon (1-5) is < 0,95 (ellenőrizve 2026-10-11)."""
    rng = np.random.default_rng(3)
    bars = pd.concat([synth_bars(6 * 365 * 3, seed=300 + k, trend=False).assign(symbol=s, funding_rate=0.0)
                      for k, s in enumerate(["A", "B", "C", "D", "E", "F"])]).set_index(["symbol", "ts"]).sort_index()
    strat = registry.load("trend-ema-cross-4h-01")
    reg = align_regime(pd.DataFrame(), bars.index)
    costs, risk = Costs(0.00045, 0.0002, 0.05), RiskParams(0.01, 2.0, 0.5, 99, 100, 100)
    rets = {}
    for k in range(100):
        fast = int(rng.integers(3, 40))
        p = {"fast": fast, "slow": int(fast + rng.integers(5, 150)), "atr_n": int(rng.integers(5, 30)),
             "atr_stop": float(rng.uniform(1.0, 5.0))}
        res = engine.run(bars, strat.with_params(p).signals(bars, reg), "4h", costs, risk)
        rets[f"v{k}"] = daily_returns(res.equity, res.initial_capital)
    trials = pd.DataFrame(rets)
    best = max(trials, key=lambda c: dsr.sr(trials[c]))
    naive = dsr.deflated_sharpe(trials[best])               # mintha csak ezt az egyet próbáltuk volna
    deflated = dsr.deflated_sharpe(trials[best], trials)    # a 100 kísérlettel
    assert naive["dsr"] > 0.95                              # a túlillesztett nyertes naivan „szignifikáns”
    assert deflated["n_trials"] == 100 and deflated["sr0"] > 0
    assert deflated["dsr"] < 0.95


# ---------------------------------------------------------------- CPCV, PBO, walk-forward


def test_cpcv_28_combinations_with_purge_and_embargo():
    days = pd.date_range("2021-01-01", periods=800, freq="D", tz="UTC")
    sp = cpcv.splits(days, 8, 2, purge_days=7, embargo_days=3)
    assert len(sp) == 28
    train, test = sp[0]  # 0. és 1. blokk a teszt
    assert test[:200].all() and not test[200:].any()
    # 1. teszt-blokk: 100..199. nap -> a tanulóból kiesik 93..202 (7 nap tisztítás, 3 nap embargó)
    assert not train[:203].any() and train[203]
    assert not (train & test).any()


def test_pbo_low_for_real_edge_high_for_noise():
    rng = np.random.default_rng(3)
    days = pd.date_range("2021-01-01", periods=1000, freq="D", tz="UTC")
    edge = pd.DataFrame({f"v{k}": 0.0005 * (k + 1) + 0.01 * rng.standard_normal(1000) for k in range(6)},
                        index=days)  # v5 végig a legjobb
    noise = pd.DataFrame({f"v{k}": 0.01 * rng.standard_normal(1000) for k in range(20)}, index=days)
    cfg_cpcv = {"n_blocks": 8, "k_test": 2, "purge_days": 7, "embargo_days": 3}
    assert pbo.pbo(edge, cfg_cpcv)["pbo"] < 0.2
    assert 0.25 < pbo.pbo(noise, cfg_cpcv)["pbo"] < 0.8
    assert pbo.pbo(edge[["v0"]], cfg_cpcv)["pbo"] is None


def test_walkforward_windows_and_ratio():
    idx = (T0 + DAY * np.arange(1, 3 * 365)).astype("int64")
    rng = np.random.default_rng(4)
    r = pd.Series(0.001 + 0.01 * rng.standard_normal(len(idx)), index=idx)
    wf = walkforward.evaluate(r, 365, {"is_months": 12, "oos_months": 3, "step_months": 3})
    # 2021-01-02 – 2023-12-31: a 15 hónapos ablak 3 havonta lépve 7-szer fér bele (a 8. 2024-01-02-ig érne)
    assert wf["windows"] == 7
    assert wf["oos_is_ratio"] == pytest.approx(wf["oos_sharpe_median"] / wf["is_sharpe_median"])


# ---------------------------------------------------------------- kapuk


def _ev(**over):
    ev = {"metrics": {"status": "ok", "trades": 150, "max_dd": 0.1,
                      "regime_ev": {"up/high": {"trades": 10, "ev": 1.0}, "down/high": {"trades": 5, "ev": 2.0}}},
          "pf_2x": 1.5, "walkforward": {"oos_is_ratio": 0.8}, "dsr": {"dsr": 0.97}, "pbo": {"pbo": 0.1},
          "param_stability": {"negative": []}}
    ev.update(over)
    return ev


def test_gates_pass_and_each_failure(cfg):
    assert gates.check_l1(_ev(), cfg.judge) == ("pass", [])
    cases = {
        "kötésszám": {"metrics": {**_ev()["metrics"], "trades": 99}},
        "PF 2x": {"pf_2x": 1.29},
        "OOS/IS": {"walkforward": {"oos_is_ratio": 0.49}},
        "DSR": {"dsr": {"dsr": 0.95}},
        "PBO 0.20": {"pbo": {"pbo": 0.2}},
        "PBO nem számolható": {"pbo": {"pbo": None, "reason": "x"}},
        "rezsim": {"metrics": {**_ev()["metrics"], "regime_ev": {"up/high": {"trades": 5, "ev": 1.0}}}},
        "min. 5 kötés": {"metrics": {**_ev()["metrics"], "regime_ev": {"up/high": {"trades": 40, "ev": 1.0},
                                                                        "down/high": {"trades": 4, "ev": 9.0}}}},
        "paraméter-stabilitás": {"param_stability": {"negative": ["fast+20%"]}},
        "max DD": {"metrics": {**_ev()["metrics"], "max_dd": 0.26}},
        "failed": {"metrics": {**_ev()["metrics"], "status": "failed"}},
    }
    for needle, over in cases.items():
        result, fails = gates.check_l1(_ev(**over), cfg.judge)
        assert result == "fail" and any(needle in f for f in fails), needle


def test_perturbations_round_ints():
    p = perturbations({"fast": 20, "atr_stop": 3.0, "name": "x", "flag": True}, 20)
    assert p["fast-20%"]["fast"] == 16 and p["fast+20%"]["fast"] == 24
    assert p["atr_stop+20%"]["atr_stop"] == pytest.approx(3.6)
    assert set(p) == {"fast-20%", "fast+20%", "atr_stop-20%", "atr_stop+20%"}


# ---------------------------------------------------------------- holdout


def test_holdout_isolation(cfg):
    today = write_env(cfg, n=3000)
    cut = backtest.holdout_start(cfg, today)
    cut_ms = int(cut.timestamp() * 1000)
    assert store.read_bars(cfg, "BTCUSDT", "4h")["ts"].max() >= cut_ms  # van adat a holdoutban
    with store.holdout_locked(cut_ms):
        assert store.read_bars(cfg, "BTCUSDT", "4h")["ts"].max() < cut_ms
        assert store.read_funding(cfg, "BTCUSDT")["ts"].max() < cut_ms
        assert store.load_barframe(cfg, ["BTCUSDT"], "4h").index.get_level_values("ts").max() < cut_ms
        with pytest.raises(store.HoldoutViolation):
            store.load_barframe(cfg, ["BTCUSDT"], "4h", end_ms=cut_ms + H4)
    assert store.holdout_cut_ms() is None  # a zár a blokk után feloldódik
    bt = backtest.run(cfg, "trend-ema-cross-4h-01", today=today, write=False)
    assert bt.result.equity["ts"].max() <= cut_ms


def test_holdout_runs_once_and_burns_neighbours(cfg, tmp_path):
    root = tmp_path / "families"
    a, b, c = write_variants(root, [{"fast": 20, "slow": 100, "atr_n": 14, "atr_stop": 3.0},
                                    {"fast": 22, "slow": 110, "atr_n": 14, "atr_stop": 3.0},
                                    {"fast": 5, "slow": 30, "atr_n": 14, "atr_stop": 3.0}])
    today = write_env(cfg, n=3000)
    out = holdout.run_holdout(cfg, a, today=today, strategies_root=root)
    assert out["window_start"] == backtest.holdout_start(cfg, today).strftime("%Y-%m-%d") and out["trades"] >= 0
    with pytest.raises(holdout.HoldoutRefused, match="már lefutott"):
        holdout.run_holdout(cfg, a, today=today, strategies_root=root)
    with pytest.raises(holdout.HoldoutRefused, match="burn"):
        holdout.run_holdout(cfg, b, today=today, strategies_root=root)  # ±10%: túl közel
    holdout.run_holdout(cfg, c, today=today, strategies_root=root)       # messze van: szabad
    later = dt.datetime.now(dt.UTC) + dt.timedelta(days=31)
    holdout.run_holdout(cfg, b, today=today, strategies_root=root, now=later)  # lejárt a tiltás
    with connect(cfg.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM trials WHERE holdout_used = 1").fetchone()[0] == 3


# ---------------------------------------------------------------- teljes ítélet


def test_judge_accepts_simple(cfg, tmp_path):
    """Valódi trendet tartalmazó szintetikus adaton az EMA-kereszt minden L1 kapun átmegy."""
    root = tmp_path / "families"
    ids = write_variants(root, [
        {"fast": 20, "slow": 100, "atr_n": 14, "atr_stop": 3.0},  # a vizsgált variáns
        {"fast": 30, "slow": 150, "atr_n": 14, "atr_stop": 3.0},
        {"fast": 2, "slow": 3, "atr_n": 14, "atr_stop": 0.5},     # zajkereskedő: díjban vérzik
        {"fast": 3, "slow": 5, "atr_n": 14, "atr_stop": 0.5},
    ])
    today = write_env(cfg, symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"))
    ev = evaluate_l1(cfg, ids[0], today=today, strategies_root=root)
    assert ev["gate_result"] == "pass", ev["gate_failures"]
    assert ev["pbo"]["variants"] == 4 and ev["pbo"]["combinations"] == 28
    assert ev["elapsed_s"] < 120
    with connect(cfg.db_path) as conn:
        row = conn.execute("SELECT * FROM trials WHERE trial_id = ?", (ev["trial_id"],)).fetchone()
        kinds = dict(conn.execute("SELECT COALESCE(gate_result, '-'), COUNT(*) FROM trials GROUP BY 1").fetchall())
    assert row["gate_result"] == "pass" and row["dsr"] > 0.95 and row["pbo"] < 0.2
    assert json.loads(row["wf_metrics_json"])["windows"] > 0 and json.loads(row["gate_failures"]) == []
    assert kinds["stability_probe"] == 8 and kinds["pbo_member"] == 3  # minden signals()-futás naplózva


def test_judge_rejects_random_walk(cfg, tmp_path):
    root = tmp_path / "families"
    ids = write_variants(root, [{"fast": 20, "slow": 100, "atr_n": 14, "atr_stop": 3.0},
                                {"fast": 10, "slow": 50, "atr_n": 14, "atr_stop": 2.0}])
    today = write_env(cfg, trend=False)
    ev = evaluate_l1(cfg, ids[0], today=today, strategies_root=root)
    assert ev["gate_result"] == "fail" and ev["gate_failures"]


def test_family_trials_dedupe_by_config(cfg):
    rows = []
    for k in range(3):
        rows.append({"trial_id": f"t{k}", "strategy_id": "s", "family": "trend", "params_hash": "p" * 12,
                     "data_hash": "d", "is_metrics_json": json.dumps({"out_dir": None})})
    for r in rows:
        ledger.record(cfg, r)
    got = ledger.family_trials(cfg, "trend", 90)
    assert len(got) == 3 and ledger.trial_returns(got).shape[1] == 0  # kimenet nélkül nincs hozamsor

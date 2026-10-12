"""Visszateszt-futtató: stratégia + adat + szimulátor -> trades/equity/exposure parquet + ledger-sor.

A holdout-ablak (az utolsó `judge.yaml: holdout.months` hónap, gördülő, a futás napjától) sosem
kerül a visszatesztbe: a futás a tár holdout-zárja alatt történik (`store.holdout_locked`).
Minden `signals()`-futás egy sort ír a `trials` táblába (spec 0.3), a bukott is.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from evolab.config import Config
from evolab.data import store
from evolab.data.universe import symbols
from evolab.db import connect, init_db
from evolab.judge import ledger
from evolab.judge.metrics import daily_returns
from evolab.sim import engine
from evolab.sim.costs import Costs
from evolab.sim.risk import RiskParams
from evolab.strategy import registry
from evolab.strategy.base import align_regime


@dataclass
class BacktestRun:
    trial_id: str
    strategy_id: str
    result: engine.Result
    out_dir: Path | None
    holdout_start: pd.Timestamp
    data_hash: str
    params_hash: str
    params: dict
    cost_results: dict | None = None  # költségszorzó -> Result (ugyanazzal a jellel)


def holdout_start(cfg: Config, today: dt.date | None = None) -> pd.Timestamp:
    today = today or dt.datetime.now(dt.UTC).date()
    return pd.Timestamp(today, tz="UTC") - pd.DateOffset(months=int(cfg.judge["holdout"]["months"]))


def data_hash(bars: pd.DataFrame) -> str:
    return hashlib.sha256(pd.util.hash_pandas_object(bars, index=True).to_numpy().tobytes()).hexdigest()


def params_hash(params: dict) -> str:
    return hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()


def read_regime(cfg: Config, syms: list[str]) -> pd.DataFrame:
    if not cfg.db_path.exists():
        return pd.DataFrame(columns=["date", "symbol", "trend", "vol", "positioning"])
    with connect(cfg.db_path) as conn:
        q = f"SELECT * FROM regime_daily WHERE symbol IN ({','.join('?' * len(syms))})"
        return pd.read_sql_query(q, conn, params=syms)


def load_inputs(cfg: Config, tf: str, cut: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame]:
    """BarFrame és igazított rezsim a holdout-zár alatt."""
    syms = symbols(cfg)
    with store.holdout_locked(int(cut.timestamp() * 1000)):
        bars = store.load_barframe(cfg, syms, tf)
    return bars, align_regime(read_regime(cfg, syms), bars.index)


def simulate(cfg: Config, strat: registry.LoadedStrategy, bars: pd.DataFrame, regime: pd.DataFrame,
             cost_mults: tuple[float, ...] = (1.0,)) -> dict[float, engine.Result]:
    """Egy jel, több költségszorzó (a díj és a slippage együtt szorzódik)."""
    sig = strat.signals(bars, regime)
    risk = RiskParams.from_config(cfg.lab["risk"])
    return {m: engine.run(bars, sig, strat.meta.timeframe, Costs.from_config(cfg.lab["costs"], m), risk,
                          regime=regime) for m in cost_mults}


def run(cfg: Config, strategy_id: str, cost_mult: float = 1.0, today: dt.date | None = None,
        write: bool = True, strategies_root: Path = registry.FAMILIES_DIR, params: dict | None = None,
        bars: pd.DataFrame | None = None, regime: pd.DataFrame | None = None,
        cost_mults: tuple[float, ...] | None = None, gate_result: str | None = None) -> BacktestRun:
    """Egy visszateszt. `params`: a fájl paraméterei helyett (paraméter-stabilitás); `bars`/`regime`:
    előre betöltött bemenet (a bíró ugyanazt a sort használja minden futáshoz)."""
    strat = registry.load(strategy_id, strategies_root)
    if params is not None:
        strat = strat.with_params(params)
    cut = holdout_start(cfg, today)
    if bars is None:
        bars, regime = load_inputs(cfg, strat.meta.timeframe, cut)
    mults = cost_mults or (cost_mult,)
    results = simulate(cfg, strat, bars, regime, mults)
    bt = BacktestRun(ledger.new_trial_id(), strategy_id, results[mults[0]], None, cut, data_hash(bars),
                     params_hash(strat.meta.params), dict(strat.meta.params), results)
    if write:
        bt.out_dir = _write_outputs(cfg, bt)
        _register_strategy(cfg, strat)
        ledger.record(cfg, {
            "trial_id": bt.trial_id, "strategy_id": strategy_id, "family": strat.meta.family,
            "hypothesis_id": strat.meta.hypothesis_id, "parent_id": strat.meta.parent_id,
            "params_hash": bt.params_hash, "data_hash": bt.data_hash, "is_metrics_json": summary(bt, mults[0]),
            "gate_result": gate_result,
        })
    return bt


def summary(bt: BacktestRun, cost_mult: float) -> dict:
    eq = bt.result.equity
    return {**bt.result.summary(), "trades_hash": bt.result.trades_hash(), "cost_mult": cost_mult,
            "params": bt.params, "holdout_start": bt.holdout_start.strftime("%Y-%m-%d"),
            "first_bar": int(eq["ts"].iloc[0]) if len(eq) else None,
            "last_bar": int(eq["ts"].iloc[-1]) if len(eq) else None, "out_dir": str(bt.out_dir)}


def _write_outputs(cfg: Config, bt: BacktestRun) -> Path:
    out = store.data_dir(cfg) / "backtests" / bt.strategy_id / bt.trial_id
    rd = daily_returns(bt.result.equity, bt.result.initial_capital)
    returns = pd.DataFrame({"day": rd.index, "ret": rd.to_numpy()})
    for name, df in (("trades", bt.result.trades), ("equity", bt.result.equity),
                     ("exposure", bt.result.exposure), ("events", bt.result.events)):
        store.write_parquet(df, out / f"{name}.parquet")
    store.write_parquet(returns, out / ledger.RETURNS_FILE)
    return out


def _register_strategy(cfg: Config, strat: registry.LoadedStrategy) -> None:
    m = strat.meta
    repo = Path(registry.__file__).resolve().parents[3]  # src/evolab/strategy/registry.py -> repó
    if strat.path.is_relative_to(repo):
        rel = str(strat.path.relative_to(repo))
    elif "src" in strat.path.parts:  # fejlesztői worktree: a merge után ugyanitt lesz a repóban
        rel = str(Path(*strat.path.parts[strat.path.parts.index("src"):]))
    else:
        rel = str(strat.path)
    init_db(cfg)
    with connect(cfg.db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO strategies(strategy_id, family, parent_id, hypothesis_id, timeframe, "
            "params_json, file_path) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (m.id, m.family, m.parent_id, m.hypothesis_id, m.timeframe, json.dumps(m.params, sort_keys=True), rel),
        )

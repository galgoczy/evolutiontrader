"""Visszateszt-futtató: stratégia + adat + szimulátor -> trades/equity/exposure parquet + ledger-sor.

A holdout-ablak (az utolsó `judge.yaml: holdout.months` hónap, gördülő, a futás napjától) sosem
kerül a visszatesztbe. Minden futás egy sort ír a `trials` táblába (spec 0.3), a bukott is.
A teljes ítélet (walk-forward, CPCV, DSR, kapuk) a 3. fázisban a `judge/` csomagba kerül.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from evolab.config import Config
from evolab.data import store
from evolab.data.universe import symbols
from evolab.db import connect, init_db
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


def run(cfg: Config, strategy_id: str, cost_mult: float = 1.0, today: dt.date | None = None,
        write: bool = True, strategies_root: Path = registry.FAMILIES_DIR) -> BacktestRun:
    strat = registry.load(strategy_id, strategies_root)
    syms = symbols(cfg)
    cut = holdout_start(cfg, today)
    bars = store.load_barframe(cfg, syms, strat.meta.timeframe, end_ms=int(cut.timestamp() * 1000))
    regime = align_regime(read_regime(cfg, syms), bars.index)
    sig = strat.signals(bars, regime)
    res = engine.run(bars, sig, strat.meta.timeframe, Costs.from_config(cfg.lab["costs"], cost_mult),
                     RiskParams.from_config(cfg.lab["risk"]), regime=regime)
    trial_id = f"{dt.datetime.now(dt.UTC):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:8]}"
    bt = BacktestRun(trial_id, strategy_id, res, None, cut, data_hash(bars), params_hash(strat.meta.params))
    if write:
        bt.out_dir = _write_outputs(cfg, bt)
        _ledger(cfg, bt, strat, cost_mult)
    return bt


def _write_outputs(cfg: Config, bt: BacktestRun) -> Path:
    out = store.data_dir(cfg) / "backtests" / bt.strategy_id / bt.trial_id
    for name, df in (("trades", bt.result.trades), ("equity", bt.result.equity),
                     ("exposure", bt.result.exposure), ("events", bt.result.events)):
        store.write_parquet(df, out / f"{name}.parquet")
    return out


def _ledger(cfg: Config, bt: BacktestRun, strat, cost_mult: float) -> None:
    m = strat.meta
    metrics = {**bt.result.summary(), "trades_hash": bt.result.trades_hash(), "cost_mult": cost_mult,
               "holdout_start": bt.holdout_start.strftime("%Y-%m-%d"),
               "first_bar": int(bt.result.equity["ts"].iloc[0]) if len(bt.result.equity) else None,
               "last_bar": int(bt.result.equity["ts"].iloc[-1]) if len(bt.result.equity) else None,
               "out_dir": str(bt.out_dir)}
    init_db(cfg)
    repo = Path(registry.__file__).resolve().parents[3]  # src/evolab/strategy/registry.py -> repó
    rel = str(strat.path.relative_to(repo)) if strat.path.is_relative_to(repo) else str(strat.path)
    with connect(cfg.db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO strategies(strategy_id, family, parent_id, hypothesis_id, timeframe, "
            "params_json, file_path) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (m.id, m.family, m.parent_id, m.hypothesis_id, m.timeframe, json.dumps(m.params, sort_keys=True), rel),
        )
        conn.execute(
            "INSERT INTO trials(trial_id, strategy_id, family, hypothesis_id, parent_id, params_hash, "
            "data_hash, judge_version, is_metrics_json, holdout_used) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
            (bt.trial_id, m.id, m.family, m.hypothesis_id, m.parent_id, bt.params_hash, bt.data_hash,
             cfg.judge_version, json.dumps(metrics)),
        )

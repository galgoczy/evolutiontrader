"""L2 paper-ítélet (docs/02-specifikacio.md 6.1/2. `judge.evaluate_population`). VÉDETT.

Minden L2-es (emberi jóváhagyással paperbe léptetett) stratégia paper-mutatói a `data/paper/<id>/`
kimenetekből; ítélet a `gates.check_l2` szerint, egy ledger-sor (`gate_result` l2_pass/l2_hold/l2_demote).
Az árnyék-paper (`shadow`) nem kap ítéletet: az csak mérés.
"""

from __future__ import annotations

import json

import pandas as pd

from evolab.config import Config
from evolab.judge import gates, ledger
from evolab.judge.metrics import max_drawdown, profit_factor, regime_ev


def paper_metrics(cfg: Config, sid: str) -> dict | None:
    from evolab.live.paper_runner import paper_dir

    d = paper_dir(cfg) / sid
    if not (d / "equity.parquet").exists():
        return None
    eq = pd.read_parquet(d / "equity.parquet")
    trades = pd.read_parquet(d / "trades.parquet")
    initial = 10_000.0
    series = pd.concat([pd.Series([initial]), eq["equity"]], ignore_index=True)
    return {"trades": int(len(trades)), "profit_factor": profit_factor(trades["pnl"]) if len(trades) else 0.0,
            "max_dd": max_drawdown(series), "regime_ev": regime_ev(trades) if len(trades) else {},
            "equity": float(series.iloc[-1])}


def backtest_max_dd(cfg: Config, sid: str) -> float | None:
    from evolab.evolve.population import latest_verdicts

    v = latest_verdicts(cfg)
    row = v[v["strategy_id"] == sid]
    if row.empty:
        return None
    return float(json.loads(row["is_metrics_json"].iloc[0])["max_dd"])


def evaluate_population(cfg: Config) -> list[dict]:
    from evolab.backtest import params_hash
    from evolab.live.paper_runner import read_roster
    from evolab.strategy import registry

    out = []
    for sid, info in sorted(read_roster(cfg)["strategies"].items()):
        if info["mode"] != "L2":
            continue
        m = paper_metrics(cfg, sid)
        if m is None:
            continue
        result, reasons = gates.check_l2(m, backtest_max_dd(cfg, sid), cfg.judge)
        meta = registry.load(sid).meta
        ledger.record(cfg, {
            "trial_id": ledger.new_trial_id(), "strategy_id": sid, "family": meta.family,
            "hypothesis_id": meta.hypothesis_id, "parent_id": meta.parent_id,
            "params_hash": params_hash(meta.params), "data_hash": "paper",
            "is_metrics_json": {**m, "mode": "paper", "start_ms": info["start_ms"]},
            "gate_result": result, "gate_failures": reasons,
        })
        out.append({"strategy_id": sid, "result": result, "reasons": reasons, **m})
    return out

"""Egy variáns teljes L1 visszateszt-ítélete (docs/02-specifikacio.md 5.). VÉDETT.

Menet (minden a holdout-zár alatt betöltött, azonos adaton):
1. alapfutás 1x, 2x, 3x költséggel (ugyanaz a jel) -> mutatók, költségérzékenység;
2. walk-forward az 1x gyertyahozamon;
3. paraméter-stabilitás: minden numerikus paraméter ±perturb_pct% -> külön futás (ledger-sor);
4. PBO: az azonos hipotézis variánsai, ha csak egy van, a család összes variánsa (ledger-sorok);
5. DSR: a család elmúlt `dsr.trial_window_days` napi kísérletei (különböző konfigurációk) alapján;
6. kapuk (`gates.check_l1`) -> egyetlen ledger-sor minden mezővel.
"""

from __future__ import annotations

import datetime as dt
import time
from pathlib import Path

import pandas as pd

from evolab import backtest
from evolab.config import Config
from evolab.judge import dsr as dsr_mod
from evolab.judge import gates, ledger, metrics, pbo as pbo_mod, walkforward
from evolab.strategy import registry


def perturbations(params: dict, pct: float) -> dict[str, dict]:
    """Minden numerikus paraméter ×(1 ± pct/100) külön változatban; egész paraméter kerekítve, min. 1."""
    out = {}
    for k, v in params.items():
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            continue
        for sign in (-1, 1):
            new = v * (1 + sign * pct / 100)
            new = max(1, int(round(new))) if isinstance(v, int) else float(new)
            if new != v:
                out[f"{k}{'-' if sign < 0 else '+'}{pct:g}%"] = {**params, k: new}
    return out


def family_members(strat: registry.LoadedStrategy, root: Path) -> list[str]:
    """A PBO variáns-családja: azonos hipotézis variánsai, ha >1 van, különben a család összes variánsa."""
    same_family = []
    for sid, path in registry.discover(root).items():
        try:
            other = registry.load_file(path)
        except registry.StrategyRejected:
            continue
        if other.meta.family == strat.meta.family:
            same_family.append(other)
    hyp = strat.meta.hypothesis_id
    same_hyp = [s for s in same_family if hyp and s.meta.hypothesis_id == hyp]
    chosen = same_hyp if len(same_hyp) > 1 else same_family
    return [s.meta.id for s in chosen]


def evaluate_l1(cfg: Config, strategy_id: str, today: dt.date | None = None,
                strategies_root: Path = registry.FAMILIES_DIR, now: dt.datetime | None = None) -> dict:
    t0 = time.monotonic()
    j = cfg.judge
    strat = registry.load(strategy_id, strategies_root)
    tf = strat.meta.timeframe
    cut = backtest.holdout_start(cfg, today)
    inputs = {tf: backtest.load_inputs(cfg, tf, cut)}
    bars, regime = inputs[tf]

    # 1. alapfutás 1x/2x/3x költséggel
    main = backtest.run(cfg, strategy_id, today=today, write=False, strategies_root=strategies_root,
                        bars=bars, regime=regime, cost_mults=(1.0, 2.0, 3.0))
    res = main.result
    m = metrics.compute(res, tf)
    pf2 = metrics.profit_factor(main.cost_results[2.0].trades["pnl"])
    pf3 = metrics.profit_factor(main.cost_results[3.0].trades["pnl"])
    main.out_dir = backtest._write_outputs(cfg, main)
    backtest._register_strategy(cfg, strat)

    # 2. walk-forward
    wf = walkforward.evaluate(metrics.bar_returns(res.equity, res.initial_capital),
                              metrics.bars_per_year(tf), j["walkforward"])

    # 3. paraméter-stabilitás
    ps_cfg = j["L1_backtest"]["param_stability"]
    stab = {"perturb_pct": ps_cfg["perturb_pct"], "results": {}, "negative": []}
    for name, params in perturbations(strat.meta.params, ps_cfg["perturb_pct"]).items():
        run = backtest.run(cfg, strategy_id, today=today, strategies_root=strategies_root, params=params,
                           bars=bars, regime=regime, gate_result="stability_probe")
        ret = run.result.summary()["total_return_pct"]
        stab["results"][name] = ret
        if ret <= 0:
            stab["negative"].append(name)

    # 4. PBO a variáns-családon
    rets = {strategy_id: metrics.daily_returns(res.equity, res.initial_capital)}
    for sid in family_members(strat, strategies_root):
        if sid in rets:
            continue
        other_tf = registry.load(sid, strategies_root).meta.timeframe
        if other_tf not in inputs:
            inputs[other_tf] = backtest.load_inputs(cfg, other_tf, cut)
        b, r = inputs[other_tf]
        run = backtest.run(cfg, sid, today=today, strategies_root=strategies_root, bars=b, regime=r,
                           gate_result="pbo_member")
        rets[sid] = metrics.daily_returns(run.result.equity, run.result.initial_capital)
    pbo = pbo_mod.pbo(pd.DataFrame(rets), j["cpcv"])

    # 5. DSR a család kísérletein (a mostani futás is benne van)
    rows = ledger.family_trials(cfg, strat.meta.family, j["dsr"]["trial_window_days"], now)
    trials = ledger.trial_returns(rows)
    own = rets[strategy_id]
    trials[f"{strategy_id}|{main.params_hash[:12]}"] = own
    dsr = dsr_mod.deflated_sharpe(own, trials)

    ev = {"strategy_id": strategy_id, "trial_id": main.trial_id, "metrics": m, "pf_1x": m["profit_factor"],
          "pf_2x": pf2, "pf_3x": pf3, "walkforward": wf, "param_stability": stab, "pbo": pbo, "dsr": dsr,
          "holdout_start": cut.strftime("%Y-%m-%d"), "out_dir": str(main.out_dir)}
    result, failures = gates.check_l1(ev, j)
    ev["elapsed_s"] = round(time.monotonic() - t0, 1)
    ev["gate_result"], ev["gate_failures"] = result, failures

    # 6. egyetlen ledger-sor az ítélettel
    ledger.record(cfg, {
        "trial_id": main.trial_id, "strategy_id": strategy_id, "family": strat.meta.family,
        "hypothesis_id": strat.meta.hypothesis_id, "parent_id": strat.meta.parent_id,
        "params_hash": main.params_hash, "data_hash": main.data_hash,
        "is_metrics_json": {**m, "pf_2x": pf2, "pf_3x": pf3, "params": main.params, "out_dir": str(main.out_dir),
                            "holdout_start": ev["holdout_start"], "param_stability": stab,
                            "trades_hash": res.trades_hash(), "elapsed_s": ev["elapsed_s"]},
        "wf_metrics_json": wf, "cpcv_json": pbo, "dsr": dsr["dsr"], "pbo": pbo["pbo"],
        "gate_result": result, "gate_failures": failures,
    })
    return ev

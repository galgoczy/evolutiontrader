"""Holdout-futás (docs/02-specifikacio.md 5.6 `L1_holdout`). VÉDETT.

- Variánsonként (stratégia + paraméter-hash) EGYSZER futtatható; a futás a ledgerben
  `holdout_used = 1` sorral rögzül, az eredménytől függetlenül.
- Burn-szabály: ha a családban az elmúlt `cooldown_days` napban volt holdout-futás egy olyan
  változaton, amelynek minden közös numerikus paramétere legfeljebb `same_family_param_delta_pct`
  százalékkal tér el, az új futás tilos (a holdout „elégett” erre a környékre).
- A jel a teljes adaton (holdout-ablakkal együtt) számolódik, hogy a mozgóátlagok bemelegedjenek;
  a szimulátor csak a holdout-ablak gyertyáin kereskedik.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pandas as pd

from evolab import backtest
from evolab.config import Config
from evolab.data import store
from evolab.data.universe import symbols
from evolab.judge import ledger, metrics
from evolab.sim import engine
from evolab.sim.costs import Costs
from evolab.sim.risk import RiskParams
from evolab.strategy import registry
from evolab.strategy.base import align_regime


class HoldoutRefused(RuntimeError):
    pass


def _close(a: dict, b: dict, pct: float) -> bool:
    keys = [k for k in a if k in b and isinstance(a[k], (int, float)) and not isinstance(a[k], bool)]
    if not keys:
        return a == b
    return all(abs(a[k] - b[k]) <= pct / 100 * max(abs(a[k]), 1e-12) for k in keys)


def check_allowed(cfg: Config, strat: registry.LoadedStrategy, p_hash: str, now: dt.datetime) -> None:
    rule = cfg.judge["L1_holdout"]["burn_rule"]
    uses = ledger.holdout_uses(cfg, strat.meta.family)
    for _, u in uses.iterrows():
        info = json.loads(u["holdout_metrics_json"] or "{}")
        if u["strategy_id"] == strat.meta.id and u["params_hash"] == p_hash:
            raise HoldoutRefused(f"{strat.meta.id}: a holdout már lefutott erre a variánsra ({u['created_at']})")
        when = pd.Timestamp(u["created_at"]).tz_localize(None) if pd.Timestamp(u["created_at"]).tzinfo else \
            pd.Timestamp(u["created_at"])
        recent = when > pd.Timestamp(now.replace(tzinfo=None)) - pd.Timedelta(days=rule["cooldown_days"])
        if recent and _close(strat.meta.params, info.get("params", {}), rule["same_family_param_delta_pct"]):
            raise HoldoutRefused(
                f"{strat.meta.id}: burn-szabály – {u['strategy_id']} holdoutja {u['created_at']}-kor futott "
                f"±{rule['same_family_param_delta_pct']}%-on belüli paraméterekkel, {rule['cooldown_days']} napos tiltás")


def run_holdout(cfg: Config, strategy_id: str, today: dt.date | None = None,
                strategies_root: Path = registry.FAMILIES_DIR, now: dt.datetime | None = None) -> dict:
    now = now or dt.datetime.now(dt.UTC)
    strat = registry.load(strategy_id, strategies_root)
    p_hash = backtest.params_hash(strat.meta.params)
    check_allowed(cfg, strat, p_hash, now)
    tf = strat.meta.timeframe
    cut = backtest.holdout_start(cfg, today)
    cut_ms = int(cut.timestamp() * 1000)
    end_ms = int(pd.Timestamp(today or now.date(), tz="UTC").timestamp() * 1000)
    syms = symbols(cfg)
    bars = store.load_barframe(cfg, syms, tf, end_ms=end_ms)
    regime = align_regime(backtest.read_regime(cfg, syms), bars.index)
    sig = strat.signals(bars, regime)
    window = bars.index.get_level_values("ts") >= cut_ms
    res = engine.run(bars[window], sig[window], tf, Costs.from_config(cfg.lab["costs"]),
                     RiskParams.from_config(cfg.lab["risk"]), regime=regime[window])
    pf = metrics.profit_factor(res.trades["pnl"]) if len(res.trades) else 0.0
    passed = pf >= cfg.judge["L1_holdout"]["pf_min"]
    info = {"params": strat.meta.params, "window_start": cut.strftime("%Y-%m-%d"),
            "window_end": pd.Timestamp(end_ms, unit="ms", tz="UTC").strftime("%Y-%m-%d"),
            "trades": int(len(res.trades)), "profit_factor": pf, **res.summary()}
    ledger.record(cfg, {
        "trial_id": ledger.new_trial_id(), "strategy_id": strategy_id, "family": strat.meta.family,
        "hypothesis_id": strat.meta.hypothesis_id, "parent_id": strat.meta.parent_id, "params_hash": p_hash,
        "data_hash": backtest.data_hash(bars[window]), "holdout_used": 1, "holdout_metrics_json": info,
        "gate_result": "holdout_pass" if passed else "holdout_fail",
        "gate_failures": [] if passed else [f"holdout PF {pf:.2f} < {cfg.judge['L1_holdout']['pf_min']}"],
    })
    return {"passed": passed, **info}

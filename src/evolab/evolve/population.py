"""Induló populáció (docs/02-specifikacio.md 3.1, 10. – 4. fázis): minden regisztrált variáns L1-ítélete.

`seed()` két menetben fut:
1. minden variáns alapfuttatása (ledger-sor `gate_result = 'seed'`), hogy a DSR minden variánsnál
   ugyanazt a kísérletszámot lássa, ne a futtatási sorrend döntsön;
2. minden variáns teljes L1-ítélete (`judge.evaluate.evaluate_l1`).
`report()` a ledgerből olvas: variánsonként a legutolsó ítélet, családonként az átmentek száma.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pandas as pd

from evolab import backtest
from evolab.config import Config
from evolab.db import connect
from evolab.judge.evaluate import evaluate_l1
from evolab.judge.gates import positive_regimes
from evolab.strategy import registry



def seed(cfg: Config, today: dt.date | None = None, root: Path = registry.FAMILIES_DIR, log=print) -> list[dict]:
    ids = list(registry.discover(root))
    cut = backtest.holdout_start(cfg, today)
    cache: dict[str, tuple] = {}
    log(f"1/2 alapfuttatás: {len(ids)} variáns")
    for sid in ids:
        tf = registry.load(sid, root).meta.timeframe
        if tf not in cache:
            cache[tf] = backtest.load_inputs(cfg, tf, cut)
        backtest.run(cfg, sid, today=today, strategies_root=root, bars=cache[tf][0], regime=cache[tf][1],
                     gate_result="seed")
    log(f"2/2 L1-ítélet: {len(ids)} variáns")
    out = []
    for k, sid in enumerate(ids, 1):
        ev = evaluate_l1(cfg, sid, today=today, strategies_root=root)
        out.append(ev)
        log(f"  [{k:>2}/{len(ids)}] {sid:<34} {ev['gate_result'].upper():<4} {ev['elapsed_s']:>5} mp")
    return out


def latest_verdicts(cfg: Config) -> pd.DataFrame:
    """Variánsonként a legutolsó L1-ítélet (pass/fail) a ledgerből."""
    if not cfg.db_path.exists():
        return pd.DataFrame()
    with connect(cfg.db_path) as conn:
        df = pd.read_sql_query(
            "SELECT * FROM trials WHERE gate_result IN ('pass', 'fail') ORDER BY created_at", conn)
    return df.groupby("strategy_id").tail(1).reset_index(drop=True)


def _row(r: pd.Series, min_trades: int) -> dict:
    m = json.loads(r["is_metrics_json"])
    wf = json.loads(r["wf_metrics_json"] or "{}")
    reg = m.get("regime_ev", {})
    return {
        "strategy_id": r["strategy_id"], "family": r["family"], "result": r["gate_result"], "judge_version": int(r["judge_version"]),
        "trades": m["trades"], "pf_1x": m["profit_factor"], "pf_2x": m["pf_2x"], "max_dd_pct": 100 * m["max_dd"],
        "oos_is": wf.get("oos_is_ratio"), "dsr": r["dsr"], "pbo": r["pbo"],
        "regimes_pos": positive_regimes(reg, min_trades),           # a kapu szerinti szám
        "regimes_pos_any": positive_regimes(reg, 1),                 # tájékoztató: minimum nélkül
        "failures": "; ".join(json.loads(r["gate_failures"] or "[]")),
        "out_dir": m.get("out_dir"),
    }


def report(cfg: Config) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(variánsonkénti tábla, családonkénti összesítő)."""
    v = latest_verdicts(cfg)
    if v.empty:
        return pd.DataFrame(), pd.DataFrame()
    table = pd.DataFrame([_row(r, cfg.judge['L1_backtest']['regime_min_trades']) for _, r in v.iterrows()]).sort_values(["family", "strategy_id"])
    fam = table.groupby("family").agg(variants=("strategy_id", "count"),
                                      passed=("result", lambda s: int((s == "pass").sum()))).reset_index()
    expected = {f: c["initial_variants"] for f, c in cfg.families["families"].items()}
    fam["expected"] = fam["family"].map(expected)
    return table, fam


def md_table(df: pd.DataFrame) -> str:
    """Markdown-tábla külön függőség nélkül."""
    def fmt(v):
        return f"{v:.3f}" if isinstance(v, float) else ("" if v is None else str(v))
    rows = [" | ".join(df.columns)] + [" | ".join("---" for _ in df.columns)]
    rows += [" | ".join(fmt(v) for v in r) for r in df.itertuples(index=False)]
    return "\n".join(f"| {r} |" for r in rows)


def write_report(cfg: Config, table: pd.DataFrame, fam: pd.DataFrame) -> Path:
    path = cfg.path("reports") / "phase4_l1.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# Induló populáció – L1-ítéletek ({dt.date.today()})", "", "## Családonként", "",
             md_table(fam), "", "## Variánsonként", "", md_table(table)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path

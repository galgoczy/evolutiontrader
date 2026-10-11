"""Kapuk (docs/02-specifikacio.md 5.6). VÉDETT. Minden küszöb a `config/judge.yaml`-ból jön.

Az L1 visszateszt-kapu feltételei (mind kell):
- kötésszám >= min_trades
- profit factor 2x költségnél >= pf_min_at_2x_cost
- max. drawdown (mark-equity) <= max_dd_pct
- walk-forward OOS/IS arány >= oos_is_ratio_min
- DSR > dsr_min
- PBO < pbo_max (ha nem számolható, a kapu elbukik: nincs bizonyíték a túlillesztés ellen)
- legalább regimes_positive_min trend×vol kombinációban pozitív várható érték (belépéskori címke)
- paraméter-stabilitás: minden ±perturb_pct% paraméterváltozat nettó eredménye pozitív
- a futás nem állt le heti DD-megszakítóval (`failed`)
"""

from __future__ import annotations


def check_l1(ev: dict, judge_cfg: dict) -> tuple[str, list[str]]:
    """`ev`: a `judge.evaluate.evaluate_l1` összesítője. Visszaad: ('pass'|'fail', hibák listája)."""
    g = judge_cfg["L1_backtest"]
    m, fails = ev["metrics"], []
    if m["status"] == "failed":
        fails.append("megszakító: heti DD miatt leállt (failed)")
    if m["trades"] < g["min_trades"]:
        fails.append(f"kötésszám {m['trades']} < {g['min_trades']}")
    if ev["pf_2x"] < g["pf_min_at_2x_cost"]:
        fails.append(f"PF 2x költségnél {ev['pf_2x']:.2f} < {g['pf_min_at_2x_cost']}")
    if 100 * m["max_dd"] > g["max_dd_pct"]:
        fails.append(f"max DD {100 * m['max_dd']:.1f}% > {g['max_dd_pct']}%")
    if ev["walkforward"]["oos_is_ratio"] < g["oos_is_ratio_min"]:
        fails.append(f"OOS/IS {ev['walkforward']['oos_is_ratio']:.2f} < {g['oos_is_ratio_min']}")
    if not ev["dsr"]["dsr"] > g["dsr_min"]:
        fails.append(f"DSR {ev['dsr']['dsr']:.3f} <= {g['dsr_min']}")
    p = ev["pbo"]["pbo"]
    if p is None:
        fails.append(f"PBO nem számolható ({ev['pbo'].get('reason', '')})")
    elif not p < g["pbo_max"]:
        fails.append(f"PBO {p:.2f} >= {g['pbo_max']}")
    n_pos = sum(1 for v in m["regime_ev"].values() if v["ev"] > 0)
    if n_pos < g["regimes_positive_min"]:
        fails.append(f"pozitív rezsim-kombináció {n_pos} < {g['regimes_positive_min']}")
    st = ev["param_stability"]
    if g["param_stability"]["must_stay_positive"] and st["negative"]:
        fails.append(f"paraméter-stabilitás: negatív lett {', '.join(st['negative'])}")
    return ("pass" if not fails else "fail"), fails

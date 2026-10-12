"""Kapuk (docs/02-specifikacio.md 5.6). VÉDETT. Minden küszöb a `config/judge.yaml`-ból jön.

Az L1 visszateszt-kapu feltételei (mind kell):
- kötésszám >= min_trades
- profit factor 2x költségnél >= pf_min_at_2x_cost
- max. drawdown (mark-equity) <= max_dd_pct
- walk-forward OOS/IS arány >= oos_is_ratio_min
- DSR > dsr_min
- PBO < pbo_max (ha nem számolható, a kapu elbukik: nincs bizonyíték a túlillesztés ellen)
- legalább regimes_positive_min trend×vol kombinációban pozitív várható érték (belépéskori címke);
  csak a legalább regime_min_trades kötésű kombináció számít (judge.yaml v2)
- paraméter-stabilitás: minden ±perturb_pct% paraméterváltozat nettó eredménye pozitív
- a futás nem állt le heti DD-megszakítóval (`failed`)
"""

from __future__ import annotations


def positive_regimes(regime_ev: dict, min_trades: int) -> int:
    """Pozitív átlagú trend×vol kombinációk száma, csak a legalább `min_trades` kötésűek."""
    return sum(1 for v in regime_ev.values() if v["ev"] > 0 and v["trades"] >= min_trades)


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
    n_pos = positive_regimes(m["regime_ev"], g["regime_min_trades"])
    if n_pos < g["regimes_positive_min"]:
        fails.append(f"pozitív rezsim-kombináció (min. {g['regime_min_trades']} kötés) {n_pos} "
                     f"< {g['regimes_positive_min']}")
    st = ev["param_stability"]
    if g["param_stability"]["must_stay_positive"] and st["negative"]:
        fails.append(f"paraméter-stabilitás: negatív lett {', '.join(st['negative'])}")
    return ("pass" if not fails else "fail"), fails


def check_l2(paper: dict, backtest_max_dd: float | None, judge_cfg: dict) -> tuple[str, list[str]]:
    """L2 paper-kapu (spec 5.6 `L2_paper`). `paper`: trades, profit_factor, max_dd (0..1), regime_ev.

    Visszaad: ('l2_pass' | 'l2_hold' | 'l2_demote', okok).
    - DD-arány (paper max DD / visszateszt max DD) > dd_ratio_above: azonnali visszaléptetés, kötésszámtól
      függetlenül (egy katasztrofális visszaesés nem vár 200 kötést);
    - min_trades alatt: 'l2_hold' (gyűjt);
    - min_trades felett: PF < demote_if.pf_below -> 'l2_demote'; minden feltétel teljesül -> 'l2_pass'
      (az L3-hoz emberi jóváhagyás kell); különben 'l2_hold'.
    """
    g = judge_cfg["L2_paper"]
    ratio = paper["max_dd"] / backtest_max_dd if backtest_max_dd else 0.0
    if ratio > g["demote_if"]["dd_ratio_above"]:
        return "l2_demote", [f"DD-arány {ratio:.2f} > {g['demote_if']['dd_ratio_above']}"]
    if paper["trades"] < g["min_trades"]:
        return "l2_hold", [f"kötésszám {paper['trades']} < {g['min_trades']} (gyűjt)"]
    if paper["profit_factor"] < g["demote_if"]["pf_below"]:
        return "l2_demote", [f"PF {paper['profit_factor']:.2f} < {g['demote_if']['pf_below']}"]
    fails = []
    if paper["profit_factor"] < g["pf_min"]:
        fails.append(f"PF {paper['profit_factor']:.2f} < {g['pf_min']}")
    n_reg = positive_regimes(paper["regime_ev"], judge_cfg["L1_backtest"]["regime_min_trades"])
    if n_reg < g["min_regimes"]:
        fails.append(f"pozitív rezsim {n_reg} < {g['min_regimes']}")
    if ratio > g["dd_vs_backtest_max_ratio"]:
        fails.append(f"DD-arány {ratio:.2f} > {g['dd_vs_backtest_max_ratio']}")
    return ("l2_pass", []) if not fails else ("l2_hold", fails)

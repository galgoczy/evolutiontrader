"""Napi riport (docs/02-specifikacio.md 6.1/3., 8.): `reports/YYYY-MM-DD.md` + `.json`.

Minden szám a ledgerből (`trials`), a stratégia-táblából, a paper-kimenetekből és a rögzítő
pillanatképeiből jön, nem külön számolva. Tartalom: populáció és L1-ítéletek, létra, élő paper
(egyezés a visszateszttel), mért slippage, mai rezsim, kísérletszám és DSR-küszöb, rögzítő.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pandas as pd

from evolab.config import Config
from evolab.db import connect
from evolab.evolve import population
from evolab.judge import dsr as dsr_mod
from evolab.live import paper_runner as pr


def _levels(cfg: Config) -> dict:
    if not cfg.db_path.exists():
        return {}
    with connect(cfg.db_path) as conn:
        return {r["level"]: r["n"] for r in conn.execute("SELECT level, COUNT(*) n FROM strategies GROUP BY level")}


def _regime_today(cfg: Config) -> list[dict]:
    if not cfg.db_path.exists():
        return []
    with connect(cfg.db_path) as conn:
        rows = conn.execute("SELECT r.* FROM regime_daily r JOIN (SELECT symbol, MAX(date) d FROM regime_daily "
                            "GROUP BY symbol) m ON r.symbol = m.symbol AND r.date = m.d ORDER BY r.symbol").fetchall()
    return [dict(r) for r in rows]


def _trial_counts(cfg: Config) -> list[dict]:
    """Családonként a 90 napos ablak különböző konfigurációi és a belőlük adódó DSR-küszöb (SR0)."""
    from evolab.judge import ledger

    days = cfg.judge["dsr"]["trial_window_days"]
    out = []
    for fam in cfg.families["families"]:
        rows = ledger.family_trials(cfg, fam, days)
        configs = rows.drop_duplicates(["strategy_id", "params_hash"]) if not rows.empty else rows
        trials = ledger.trial_returns(rows)
        if trials.shape[1] > 1:
            n_eff = dsr_mod.effective_trials(trials)
            sr_var = float(pd.Series([dsr_mod.sr(trials[c].dropna()) for c in trials]).var(ddof=1))
            sr0 = dsr_mod.expected_max_sr(sr_var, n_eff)
        else:
            n_eff, sr0 = float(trials.shape[1]), 0.0
        out.append({"family": fam, "runs": int(len(rows)), "configs": int(len(configs)), "n_eff": round(n_eff, 1),
                    "sr0_daily": sr0, "sr0_annual": sr0 * 365 ** 0.5})
    return out


def build(cfg: Config, today: dt.date | None = None) -> dict:
    from evolab.live.recorder import health

    today = today or dt.date.today()
    table, fam = population.report(cfg)
    roster = pr.read_roster(cfg)["strategies"]
    cache: dict = {}
    paper = []
    for sid, info in sorted(roster.items()):
        s = pr.read_summary(cfg, sid) or {}
        try:
            c = pr.compare(cfg, sid, cache)
        except Exception as e:  # a riport ne bukjon el egy hiányzó adatsor miatt
            c = {"diff_pct": None, "ok": None, "days": 0.0, "error": str(e)}
        paper.append({"strategy_id": sid, "mode": info["mode"], **{k: s.get(k) for k in
                      ("trades", "open_positions", "return_pct", "max_dd_pct", "equity")},
                      "days": c.get("days"), "diff_pct": c.get("diff_pct"), "match_ok": c.get("ok"),
                      "final_check": c.get("final_check", False)})
    approvals = [] if table.empty else table[table["result"] == "pass"]["strategy_id"].tolist()
    rec = health(cfg, 24)
    return {
        "date": today.isoformat(),
        "judge_version": cfg.judge_version,
        "families": fam.to_dict("records") if not fam.empty else [],
        "variants": table.to_dict("records") if not table.empty else [],
        "levels": _levels(cfg),
        "awaiting_approval": approvals,
        "paper": paper,
        "slippage": pr.measured_slippage(cfg).to_dict("records"),
        "regime": _regime_today(cfg),
        "trial_counts": _trial_counts(cfg),
        "recorder": {sym: {"coverage": h["coverage"], "max_gap_min": h["max_gap_min"]} for sym, h in rec.items()},
    }


def _f(v, fmt="{:.2f}", none="-"):
    return none if v is None or (isinstance(v, float) and v != v) else fmt.format(v)


def to_markdown(r: dict) -> str:
    L = [f"# EvolutionTrader napi riport – {r['date']}", "", f"Bíró: `judge.yaml` v{r['judge_version']}", ""]
    L += ["## Populáció (L1)", "", "| család | variáns | átment |", "|---|---|---|"]
    L += [f"| {f['family']} | {f['variants']} | {f['passed']} |" for f in r["families"]]
    top = sorted(r["variants"], key=lambda v: -(v["dsr"] or 0))[:5]
    L += ["", "Legjobb 5 DSR szerint:", "", "| variáns | ítélet | PF 2x | DSR | PBO | max DD | bukott kapuk |",
          "|---|---|---|---|---|---|---|"]
    L += [f"| {v['strategy_id']} | {v['result']} | {_f(v['pf_2x'])} | {_f(v['dsr'], '{:.3f}')} | {_f(v['pbo'])} "
          f"| {_f(v['max_dd_pct'], '{:.1f}%')} | {v['failures'] or '-'} |" for v in top]
    L += ["", "## Létra", "", ", ".join(f"{k}: {n}" for k, n in sorted(r["levels"].items())) or "-",
          "", "Jóváhagyásra vár (L1 átment, L2-be csak emberi OK-val): " + (", ".join(r["awaiting_approval"]) or "nincs")]
    L += ["", "## Élő paper (Hyperliquid) és egyezés a visszateszttel", "",
          "| stratégia | mód | nap | kötés | nyitott | hozam | max DD | eltérés a visszateszttől |",
          "|---|---|---|---|---|---|---|---|"]
    for p in r["paper"]:
        match = "-" if p["match_ok"] is None else ("OK" if p["match_ok"] else "**ELTÉR**")
        L.append(f"| {p['strategy_id']} | {p['mode']} | {_f(p['days'], '{:.1f}')} | {p['trades'] or 0} | "
                 f"{p['open_positions'] or 0} | {_f(p['return_pct'], '{:+.2f}%')} | {_f(p['max_dd_pct'], '{:.1f}%')} | "
                 f"{_f(p['diff_pct'], '{:.2f}%')} {match}{' (végleges)' if p['final_check'] else ''} |")
    L += ["", "## Slippage: mért (Hyperliquid impact, 7 nap medián) vs. modell", "",
          "| coin | minta | mért | mért p95 | modell (4h) |", "|---|---|---|---|---|"]
    L += [f"| {s['symbol']} | {s['samples']} | {_f(s.get('measured_pct'), '{:.4f}%')} | "
          f"{_f(s.get('measured_p95_pct'), '{:.4f}%')} | {_f(s.get('model_pct'), '{:.4f}%')} |" for s in r["slippage"]]
    L += ["", "## Rezsim (legutolsó napi címke)", "", "| coin | nap | trend | vol | pozícionáltság |",
          "|---|---|---|---|---|"]
    L += [f"| {g['symbol']} | {g['date']} | {g['trend']} | {g['vol']} | {g['positioning']} |" for g in r["regime"]]
    L += ["", "## Kísérletszám és DSR-küszöb (90 nap)", "",
          "A DSR azt kérdezi, mekkora Sharpe várható pusztán a szerencse miatt ennyi kísérlet legjobbikánál (SR0); "
          "egy variáns csak akkor megy át, ha a saját Sharpe-ja ennél szignifikánsan nagyobb.", "",
          "| család | futás | konfiguráció | hatékony N | SR0 (évesített) |", "|---|---|---|---|---|"]
    L += [f"| {t['family']} | {t['runs']} | {t['configs']} | {t['n_eff']} | {_f(t['sr0_annual'])} |"
          for t in r["trial_counts"]]
    L += ["", "## Rögzítő (24 óra)", "", " · ".join(f"{s}: {100 * h['coverage']:.1f}% (rés {h['max_gap_min']:.0f} p)"
                                                   for s, h in r["recorder"].items())]
    return "\n".join(L) + "\n"


def telegram_text(r: dict) -> str:
    passed = sum(f["passed"] for f in r["families"])
    total = sum(f["variants"] for f in r["families"])
    worst = [p for p in r["paper"] if p["match_ok"] is False]
    lines = [f"📊 Napi riport {r['date']}", f"L1: {passed}/{total} átment",
             f"Jóváhagyásra vár: {', '.join(r['awaiting_approval']) or 'nincs'}",
             f"Paper: {len(r['paper'])} stratégia, eltérő: {len(worst)}"]
    cov = min((h["coverage"] for h in r["recorder"].values()), default=0.0)
    lines.append(f"Rögzítő 24h: {100 * cov:.1f}%")
    return "\n".join(lines)


def write(cfg: Config, r: dict) -> tuple[Path, Path]:
    out = cfg.path("reports")
    out.mkdir(parents=True, exist_ok=True)
    md, js = out / f"{r['date']}.md", out / f"{r['date']}.json"
    md.write_text(to_markdown(r), encoding="utf-8")
    js.write_text(json.dumps(r, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return md, js

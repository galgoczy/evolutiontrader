"""Előléptetési létra (docs/02-specifikacio.md 6.4; koncepció 5.).

Szintek: L0 (új) -> L1 (visszateszt-kapun át, várólistán) -> L2 (élő paper) -> L3 (mikro-éles) -> L4.
- L0 -> L1 és a visszalépések automatikusak (a bíró dönt, `actor = judge`);
- L1 -> L2, L2 -> L3, L3 -> L4 csak emberi jóváhagyással (`/approve`, `actor = human`); az L1 -> L2
  jóváhagyás előbb lefuttatja az egyszeri holdout-próbát, és csak annak átmenésével léptet;
- a várólista (L1) `approval.waitlist_days` nap után lejár: vissza L0-ba (a ledger-sor marad);
- L2-ből a paper-ítélet `l2_demote` esetén `retired` (kiesik a paperből).
Minden szintváltás egy sor a csak beszúrható `ladder_events` táblában.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd

from evolab.config import Config
from evolab.db import connect, init_db
from evolab.evolve.population import latest_verdicts


class LadderError(ValueError):
    pass


def level(cfg: Config, sid: str) -> str | None:
    with connect(cfg.db_path) as conn:
        row = conn.execute("SELECT level FROM strategies WHERE strategy_id = ?", (sid,)).fetchone()
    return row["level"] if row else None


def set_level(cfg: Config, sid: str, to: str, reason: str, actor: str) -> None:
    init_db(cfg)
    with connect(cfg.db_path) as conn:
        cur = conn.execute("SELECT level FROM strategies WHERE strategy_id = ?", (sid,)).fetchone()
        if cur is None:
            raise LadderError(f"ismeretlen stratégia: {sid}")
        conn.execute("INSERT INTO ladder_events(strategy_id, from_level, to_level, reason, actor) VALUES (?,?,?,?,?)",
                     (sid, cur["level"], to, reason, actor))
        conn.execute("UPDATE strategies SET level = ?, status = ? WHERE strategy_id = ?",
                     (to, "retired" if to == "retired" else "active", sid))


def _latest_gate(cfg: Config, sid: str, kinds: tuple[str, ...]) -> str | None:
    with connect(cfg.db_path) as conn:
        row = conn.execute(f"SELECT gate_result FROM trials WHERE strategy_id = ? AND gate_result IN "
                           f"({','.join('?' * len(kinds))}) ORDER BY created_at DESC LIMIT 1", (sid, *kinds)).fetchone()
    return row["gate_result"] if row else None


def waiting(cfg: Config) -> pd.DataFrame:
    """A várólista: L1-es stratégiák, mióta várnak."""
    if not cfg.db_path.exists():
        return pd.DataFrame(columns=["strategy_id", "family", "since"])
    with connect(cfg.db_path) as conn:
        return pd.read_sql_query(
            "SELECT s.strategy_id, s.family, MAX(e.created_at) since FROM strategies s JOIN ladder_events e "
            "ON e.strategy_id = s.strategy_id AND e.to_level = 'L1' WHERE s.level = 'L1' GROUP BY s.strategy_id "
            "ORDER BY since", conn)


def apply(cfg: Config, now: dt.datetime | None = None, paper_verdicts: list[dict] | None = None) -> dict:
    """Automatikus szintváltások: L1-ítéletek, várólista-lejárat, paper-visszaléptetés."""
    now = now or dt.datetime.now(dt.UTC)
    init_db(cfg)
    changes = []
    v = latest_verdicts(cfg)
    if not v.empty:
        v = v[v["judge_version"] == cfg.judge_version]
    for r in v.itertuples():
        lvl = level(cfg, r.strategy_id)
        if lvl == "L0" and r.gate_result == "pass":
            set_level(cfg, r.strategy_id, "L1", f"L1 visszateszt-kapu átment (trial {r.trial_id})", "judge")
            changes.append((r.strategy_id, "L0", "L1"))
        elif lvl == "L1" and r.gate_result == "fail":
            set_level(cfg, r.strategy_id, "L0", f"az újabb L1-ítélet elbukott (trial {r.trial_id})", "judge")
            changes.append((r.strategy_id, "L1", "L0"))
    limit = pd.Timestamp(now.replace(tzinfo=None)) - pd.Timedelta(days=int(cfg.lab["approval"]["waitlist_days"]))
    for r in waiting(cfg).itertuples():
        if pd.Timestamp(r.since.rstrip("Z")) < limit:
            set_level(cfg, r.strategy_id, "L0", f"várólista lejárt ({cfg.lab['approval']['waitlist_days']} nap)", "judge")
            changes.append((r.strategy_id, "L1", "L0"))
    for pv in paper_verdicts or []:
        if pv["result"] == "l2_demote" and level(cfg, pv["strategy_id"]) == "L2":
            set_level(cfg, pv["strategy_id"], "retired", "paper-visszaléptetés: " + "; ".join(pv["reasons"]), "judge")
            changes.append((pv["strategy_id"], "L2", "retired"))
    return {"changes": changes, "waiting": waiting(cfg)["strategy_id"].tolist()}


def holdout_result(cfg: Config, sid: str) -> dict | None:
    """A variáns (azonos paraméterekkel) korábbi holdout-futása, ha volt."""
    import json

    from evolab.backtest import params_hash
    from evolab.strategy import registry

    p_hash = params_hash(registry.load(sid).meta.params)
    with connect(cfg.db_path) as conn:
        row = conn.execute("SELECT gate_result, holdout_metrics_json FROM trials WHERE strategy_id = ? AND "
                           "params_hash = ? AND holdout_used = 1 ORDER BY created_at DESC LIMIT 1",
                           (sid, p_hash)).fetchone()
    return {"passed": row["gate_result"] == "holdout_pass", **json.loads(row["holdout_metrics_json"] or "{}")} \
        if row else None


def approve(cfg: Config, sid: str, run_holdout=None) -> str:
    """Emberi jóváhagyás: egy szinttel feljebb, ha a bíró szerint jogosult.

    L1 -> L2: az előléptetési kapunál fut a holdout (spec 5.6, koncepció 3.2), variánsonként egyszer.
    Ha még nem futott, a jóváhagyás lefuttatja; L2-be csak holdout-pass után lép, bukásnál vissza L0-ba.
    """
    lvl = level(cfg, sid)
    if lvl == "L1":
        if _latest_gate(cfg, sid, ("pass", "fail")) != "pass":
            raise LadderError(f"{sid}: a legutolsó L1-ítélet nem 'pass'")
        h = holdout_result(cfg, sid)
        if h is None:
            from evolab.judge import holdout

            try:
                h = (run_holdout or holdout.run_holdout)(cfg, sid)
            except holdout.HoldoutRefused as e:
                raise LadderError(f"{sid}: a holdout nem futtatható: {e}") from e
        summary = f"holdout PF {h.get('profit_factor', 0):.2f}, {h.get('trades', 0)} kötés"
        if not h["passed"]:
            set_level(cfg, sid, "L0", f"holdout bukott ({summary})", "judge")
            return f"{sid}: a holdout-próba elbukott ({summary}) -> L0"
        set_level(cfg, sid, "L2", f"jóváhagyva: élő paper ({summary})", "human")
        return f"{sid}: L1 -> L2 ({summary}; a következő paper-körtől fut)"
    if lvl == "L2":
        if _latest_gate(cfg, sid, ("l2_pass", "l2_hold", "l2_demote")) != "l2_pass":
            raise LadderError(f"{sid}: a paper-ítélet még nem 'l2_pass' (L3-hoz 200 paper-kötés és a kapuk kellenek)")
        set_level(cfg, sid, "L3", "jóváhagyva: mikro-éles", "human")
        return f"{sid}: L2 -> L3 (a mikro-éles végrehajtó még nem készült el, külön specifikáció)"
    raise LadderError(f"{sid}: a(z) {lvl} szintről nincs jóváhagyható lépés")


def reject(cfg: Config, sid: str, reason: str) -> str:
    lvl = level(cfg, sid)
    if lvl != "L1":
        raise LadderError(f"{sid}: csak várólistás (L1) stratégia utasítható el, ez {lvl}")
    set_level(cfg, sid, "L0", f"elutasítva: {reason or '-'}", "human")
    return f"{sid}: elutasítva ({reason or '-'})"

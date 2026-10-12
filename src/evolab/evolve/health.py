"""A 6. fázis elfogadása (spec 10.): 7 egymást követő napi futás emberi beavatkozás nélkül,
hipotézisek a ledgerben. A `make verify-6` ezt írja ki."""

from __future__ import annotations

import datetime as dt

import pandas as pd

from evolab.config import Config
from evolab.db import connect


def daily_streak(cfg: Config, today: dt.date | None = None) -> tuple[int, pd.DataFrame]:
    """A mai napig visszafelé hány egymást követő napon volt sikeres (`ok`/`warn`) teljes napi futás."""
    today = today or dt.date.today()
    with connect(cfg.db_path) as conn:
        runs = pd.read_sql_query("SELECT run_id, step, status, message, started_at FROM runs WHERE kind = 'daily' "
                                 "ORDER BY run_id", conn)
    if runs.empty:
        return 0, runs
    # a teljes (6 lépéses) futás, nem a kézi --step, és csak amióta minden lépés valódi (nincs csonk)
    full = runs[(runs["step"].str.count(",") >= 5)
                & ~runs["message"].fillna("").str.contains("nincs megvalósítva")].copy()
    full["day"] = pd.to_datetime(full["started_at"]).dt.date
    good = set(full.loc[full["status"].isin(["ok", "warn"]), "day"])
    n, d = 0, today
    while d in good:
        n += 1
        d -= dt.timedelta(days=1)
    return n, full.groupby("day").tail(1)[["day", "run_id", "status"]].tail(10)


def hypotheses_summary(cfg: Config) -> pd.DataFrame:
    with connect(cfg.db_path) as conn:
        return pd.read_sql_query(
            "SELECT h.hypothesis_id, h.family, h.mutation_type, h.status, "
            "(SELECT COUNT(*) FROM trials t WHERE t.hypothesis_id = h.hypothesis_id) AS ledger_rows, "
            "(SELECT COUNT(DISTINCT t.strategy_id) FROM trials t WHERE t.hypothesis_id = h.hypothesis_id "
            " AND t.gate_result = 'pass') AS l1_pass "
            "FROM hypotheses h ORDER BY h.hypothesis_id DESC LIMIT 20", conn)

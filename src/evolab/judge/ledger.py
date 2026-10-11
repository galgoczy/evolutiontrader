"""Kísérletnapló (`trials` tábla, docs/02-specifikacio.md 5.5). VÉDETT. Csak beszúrás.

Minden `signals()`-futás egy sor, a bukott is. A sor `is_metrics_json` mezője tartalmazza a futás
kimeneti mappáját (`out_dir`), ahol a napi hozamsor (`returns_daily.parquet`) a DSR hatékony
kísérletszámához és a SR-szóráshoz olvasható.
A DSR kísérletszáma a KÜLÖNBÖZŐ konfigurációkat számolja: (stratégia, paraméter-hash) páronként
egyet, így ugyanannak a variánsnak az újrafuttatása (pl. napi frissítés) nem fújja fel N-t.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from pathlib import Path

import pandas as pd

from evolab.config import Config
from evolab.db import connect, init_db

COLUMNS = ["trial_id", "strategy_id", "family", "hypothesis_id", "parent_id", "params_hash", "data_hash",
           "judge_version", "is_metrics_json", "wf_metrics_json", "cpcv_json", "dsr", "pbo", "gate_result",
           "gate_failures", "holdout_used", "holdout_metrics_json"]
RETURNS_FILE = "returns_daily.parquet"


def new_trial_id() -> str:
    return f"{dt.datetime.now(dt.UTC):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:8]}"


def _json(v):
    return None if v is None else json.dumps(v, default=float)


def record(cfg: Config, row: dict) -> str:
    """Egy kísérlet beszúrása. A dict/list mezők JSON-ként kerülnek a táblába."""
    init_db(cfg)
    vals = {k: row.get(k) for k in COLUMNS}
    vals["judge_version"] = vals["judge_version"] or cfg.judge_version
    vals["holdout_used"] = int(bool(vals["holdout_used"]))
    for k in ("is_metrics_json", "wf_metrics_json", "cpcv_json", "gate_failures", "holdout_metrics_json"):
        if not isinstance(vals[k], str):
            vals[k] = _json(vals[k])
    with connect(cfg.db_path) as conn:
        conn.execute(f"INSERT INTO trials({', '.join(COLUMNS)}) VALUES ({', '.join('?' * len(COLUMNS))})",
                     [vals[k] for k in COLUMNS])
    return vals["trial_id"]


def family_trials(cfg: Config, family: str, days: int, now: dt.datetime | None = None) -> pd.DataFrame:
    """A család kísérletei az utolsó `days` napból (holdout-futások nélkül)."""
    if not cfg.db_path.exists():
        return pd.DataFrame(columns=COLUMNS + ["created_at"])
    now = now or dt.datetime.now(dt.UTC)
    since = (now - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
    with connect(cfg.db_path) as conn:
        return pd.read_sql_query(
            "SELECT * FROM trials WHERE family = ? AND created_at >= ? AND holdout_used = 0 ORDER BY created_at",
            conn, params=(family, since))


def trial_returns(rows: pd.DataFrame) -> pd.DataFrame:
    """Napi hozamok (nap × konfiguráció) a sorok kimeneti mappáiból; konfigurációnként a legutolsó."""
    cols = {}
    for _, row in rows.iterrows():
        try:
            out = json.loads(row["is_metrics_json"] or "{}").get("out_dir")
        except json.JSONDecodeError:
            out = None
        path = Path(out) / RETURNS_FILE if out else None
        if path is None or not path.exists():
            continue
        s = pd.read_parquet(path)
        cols[f"{row['strategy_id']}|{row['params_hash'][:12]}"] = pd.Series(
            s["ret"].to_numpy(), index=pd.to_datetime(s["day"], utc=True))
    return pd.DataFrame(cols)


def holdout_uses(cfg: Config, family: str) -> pd.DataFrame:
    """A család összes eddigi holdout-futása (a burn-szabályhoz)."""
    if not cfg.db_path.exists():
        return pd.DataFrame(columns=COLUMNS + ["created_at"])
    with connect(cfg.db_path) as conn:
        return pd.read_sql_query("SELECT * FROM trials WHERE family = ? AND holdout_used = 1",
                                 conn, params=(family,))

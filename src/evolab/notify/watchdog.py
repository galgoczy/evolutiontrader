"""Őr (7. fázis, hibakezelés): óránként ellenőrzi a folyamatokat, és Telegramon riaszt.

Ellenőrzések:
- rögzítő: az utolsó Hyperliquid-pillanatkép kora > `RECORDER_MAX_AGE_MIN` perc;
- paper: az utolsó paper-futás kora > `PAPER_MAX_AGE_H` óra, vagy hibával zárult;
- napi futás: az utolsó teljes napi futás kora > `DAILY_MAX_AGE_H` óra;
- lemez: a `data/` kötetén < `DISK_MIN_GB` GB szabad hely.
Ugyanaz a riasztás legfeljebb `REPEAT_H` óránként ismétlődik; ha a hiba megszűnik, egyszer „rendben”
üzenet megy. Állapot: `data/alerts.json`. A STOP kapcsoló nem riasztás (szándékos leállás).
"""

from __future__ import annotations

import datetime as dt
import json
import shutil

import pandas as pd

from evolab.config import Config
from evolab.data import store
from evolab.data.universe import symbols
from evolab.db import connect

RECORDER_MAX_AGE_MIN = 10
PAPER_MAX_AGE_H = 3
DAILY_MAX_AGE_H = 26
DISK_MIN_GB = 5
REPEAT_H = 6


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def last_tick_ms(cfg: Config) -> int | None:
    """Az utolsó rögzített pillanatkép ideje: a JSONL-puffer utolsó sora, különben a parquet."""
    buf = sorted((store.data_dir(cfg) / "hl" / "buffer").glob("ticks_*.jsonl"))
    for path in reversed(buf):
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        for line in reversed(lines):
            try:
                return int(json.loads(line)["ts"])
            except (ValueError, KeyError):
                continue
    ticks = store.read_hl_ticks(cfg, symbols(cfg)[0])
    return int(ticks["ts"].max()) if not ticks.empty else None


def _age_h(iso: str | None, now: dt.datetime) -> float | None:
    if not iso:
        return None
    t = pd.Timestamp(iso.rstrip("Z")).tz_localize("UTC")
    return (pd.Timestamp(now) - t).total_seconds() / 3600


def problems(cfg: Config, now: dt.datetime | None = None, disk_free_gb: float | None = None) -> dict[str, str]:
    """A jelenlegi hibák: kulcs -> üzenet (üres = minden rendben)."""
    now = now or _now()
    out: dict[str, str] = {}
    tick = last_tick_ms(cfg)
    age_min = (now.timestamp() * 1000 - tick) / 60_000 if tick else None
    if age_min is None or age_min > RECORDER_MAX_AGE_MIN:
        out["recorder"] = ("a rögzítő nem írt még adatot" if age_min is None
                           else f"a rögzítő {age_min:.0f} perce nem írt (launchd: com.evolutiontrader.recorder)")
    if cfg.db_path.exists():
        with connect(cfg.db_path) as conn:
            paper = conn.execute("SELECT status, message, COALESCE(finished_at, started_at) t FROM runs "
                                 "WHERE kind = 'paper' ORDER BY run_id DESC LIMIT 1").fetchone()
            daily = conn.execute("SELECT status, started_at t FROM runs WHERE kind = 'daily' "
                                 "AND step LIKE '%,%,%,%,%,%' ORDER BY run_id DESC LIMIT 1").fetchone()
        if not cfg.stop_file.exists():
            a = _age_h(paper["t"], now) if paper else None
            if a is None or a > PAPER_MAX_AGE_H:
                out["paper"] = "a paper-futás nem fut óránként" + (f" ({a:.1f} órája volt utoljára)" if a else "")
            elif paper["status"] != "ok":
                out["paper"] = f"a legutolsó paper-futás hibás: {paper['message']}"
        a = _age_h(daily["t"], now) if daily else None
        if a is None or a > DAILY_MAX_AGE_H:
            out["daily"] = "a napi futás kimaradt" + (f" ({a:.0f} órája volt utoljára)" if a else "")
    free = disk_free_gb if disk_free_gb is not None else shutil.disk_usage(store.data_dir(cfg)).free / 1e9
    if free < DISK_MIN_GB:
        out["disk"] = f"kevés a szabad hely a data/ kötetén: {free:.1f} GB"
    return out


def run(cfg: Config, send=None, now: dt.datetime | None = None, disk_free_gb: float | None = None) -> list[str]:
    """Riasztások küldése az állapotváltozások szerint. Visszaad: az elküldött üzenetek."""
    from evolab.notify import telegram

    send = send or telegram.send
    now = now or _now()
    path = store.data_dir(cfg) / "alerts.json"
    state = json.loads(path.read_text()) if path.exists() else {}
    current = problems(cfg, now, disk_free_gb)
    sent = []
    for key, msg in current.items():
        last = state.get(key)
        if last is None or _age_h(last, now) >= REPEAT_H:
            text = f"⚠️ EvolutionTrader: {msg}"
            send(text)
            sent.append(text)
            state[key] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    for key in [k for k in state if k not in current]:
        text = f"✅ EvolutionTrader: rendben ({key})"
        send(text)
        sent.append(text)
        del state[key]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2))
    return sent

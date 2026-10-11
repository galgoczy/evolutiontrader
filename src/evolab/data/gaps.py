"""Hiányzó gyertyák riportja coinonként és idősíkonként (spec 10., 1. fázis).

Minden hiányzó gyertya-sorozat (egymást követő hiányzó gyertyák) egy kategóriát kap:
- `outage`:       ismert, dokumentált Binance-leállás (docs/DONTESEK.md, „Ismert Binance-leállások”);
                  ilyenkor valóban nem volt kereskedés, a hiány nem adathiba.
- `missing_file`: a gyertya napjára/hónapjára nincs letöltött zip a gyorsítótárban.
- `gap`:          a zip megvan, de a gyertya nincs benne (vagy a CCXT-farokból hiányzik).
A `make verify-1` akkor zöld, ha az `outage`-on kívül 0 a hiány.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from evolab.config import Config
from evolab.data import store
from evolab.data.universe import symbols, tf_ms, timeframes

OUTAGE_HEADING = "## Ismert Binance-leállások"
_ROW = re.compile(r"^\|\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\s*\|\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\s*\|\s*([^|]+?)\s*\|")
COLUMNS = ["symbol", "tf", "start", "end", "bars", "kind"]


def known_outages(path: Path) -> pd.DataFrame:
    """A dokumentált leállások táblája: start, end (UTC, a vég kizárólagos), symbols ('*' = mind)."""
    rows = []
    in_section = False
    for line in path.read_text(encoding="utf-8").splitlines() if path.exists() else []:
        if line.startswith("## "):
            in_section = line.strip() == OUTAGE_HEADING
            continue
        m = _ROW.match(line) if in_section else None
        if m:
            syms = {s.strip() for s in m.group(3).split(",")}
            rows.append({"start": pd.Timestamp(m.group(1), tz="UTC"), "end": pd.Timestamp(m.group(2), tz="UTC"),
                         "symbols": syms})
    return pd.DataFrame(rows, columns=["start", "end", "symbols"])


def outages(cfg: Config) -> pd.DataFrame:
    return known_outages(cfg.root / "docs" / "DONTESEK.md")


def _runs(missing: pd.DatetimeIndex, tf: str) -> list[tuple[pd.Timestamp, pd.Timestamp, int]]:
    """Egymást követő hiányzó gyertyák összevonása: (első nyitó, utolsó zárás, darab)."""
    step = pd.Timedelta(milliseconds=tf_ms(tf))
    out: list[list] = []
    for t in missing:
        if out and t == out[-1][1]:
            out[-1][1] = t + step
            out[-1][2] += 1
        else:
            out.append([t, t + step, 1])
    return [tuple(r) for r in out]


def _zip_exists(cfg: Config, symbol: str, tf: str, t: pd.Timestamp) -> bool:
    base = store.raw_dir(cfg)
    monthly = base / "monthly" / "klines" / symbol / tf / f"{symbol}-{tf}-{t:%Y-%m}.zip"
    daily = base / "daily" / "klines" / symbol / tf / f"{symbol}-{tf}-{t:%Y-%m-%d}.zip"
    return monthly.exists() or daily.exists()


def classify(cfg: Config | None, symbol: str, tf: str, start: pd.Timestamp, end: pd.Timestamp,
             out: pd.DataFrame) -> str:
    for o in out.itertuples():
        if ("*" in o.symbols or symbol in o.symbols) and start >= o.start and end <= o.end:
            return "outage"
    if cfg is not None and not _zip_exists(cfg, symbol, tf, start):
        return "missing_file"
    return "gap"


def series_gaps(cfg: Config | None, symbol: str, tf: str, ts: pd.Series, out: pd.DataFrame) -> pd.DataFrame:
    rows = [
        {"symbol": symbol, "tf": tf, "start": a, "end": b, "bars": n,
         "kind": classify(cfg, symbol, tf, a, b, out)}
        for a, b, n in _runs(store.missing_bars(ts, tf), tf)
    ]
    return pd.DataFrame(rows, columns=COLUMNS)


def gap_report(cfg: Config) -> pd.DataFrame:
    out = outages(cfg)
    frames = []
    for sym in symbols(cfg):
        for tf in timeframes(cfg):
            df = store.read_bars(cfg, sym, tf)
            if not df.empty:
                frames.append(series_gaps(cfg, sym, tf, df["ts"], out))
    frames = [f for f in frames if not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=COLUMNS)


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    """Hiányzó gyertyák száma coinonként, idősíkonként és kategóriánként."""
    return (df.groupby(["symbol", "tf", "kind"])["bars"].sum().unstack("kind", fill_value=0)
            .reset_index().rename_axis(columns=None))


def write_report(cfg: Config, df: pd.DataFrame) -> Path:
    path = cfg.path("reports") / "data_gaps.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    return path

"""Adatminőség-ellenőrzés: a `make verify-1` elfogadási feltételei (spec 10.)."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from evolab.config import Config
from evolab.data import gaps, store
from evolab.data.binance_bulk import verify_cached
from evolab.data.universe import last_closed_open_ms, symbols, tf_ms, timeframes
from evolab.db import connect

# Ennyi gyertyányi késés még elfogadott a frissességnél (a napi futás 02:00-kor megy).
MAX_LAG_BARS = {"1h": 30, "4h": 8, "1d": 2}


@dataclass
class CheckResult:
    lines: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    def ok(self, msg: str) -> None:
        self.lines.append(f"  OK    {msg}")

    def fail(self, msg: str) -> None:
        self.lines.append(f"  HIBA  {msg}")
        self.failures.append(msg)


def _fmt(ts_ms: int) -> str:
    return pd.Timestamp(ts_ms, unit="ms", tz="UTC").strftime("%Y-%m-%d %H:%M")


def check_bars(cfg: Config, res: CheckResult, now: int | None = None) -> None:
    """Első/utolsó gyertya, darabszám, hiány. Az ismert leállás nem hiba (docs/DONTESEK.md)."""
    res.lines.append("Gyertyák (Binance USDT-M): első – utolsó, darab, hiány (ebből ismert leállás):")
    out = gaps.outages(cfg)
    res.lines.append(f"  ismert leállások a listában: {len(out)}")
    for sym in symbols(cfg):
        for tf in timeframes(cfg):
            df = store.read_bars(cfg, sym, tf)
            name = f"{sym:<9}{tf:>3}"
            if df.empty:
                res.fail(f"{name}: nincs adat")
                continue
            g = gaps.series_gaps(cfg, sym, tf, df["ts"], out)
            n_out = int(g.loc[g["kind"] == "outage", "bars"].sum())
            n_bad = int(g["bars"].sum()) - n_out
            n_mark = int(df["mark_close"].isna().sum())
            lag = (last_closed_open_ms(tf, now) - int(df["ts"].max())) // tf_ms(tf)
            msg = (f"{name}: {_fmt(df['ts'].min())} – {_fmt(df['ts'].max())}, {len(df):>6} gyertya, "
                   f"hiány {n_bad + n_out} ({n_out} leállás), mark nélkül {n_mark}")
            if n_bad:
                first = g[g["kind"] != "outage"].iloc[0]
                res.fail(msg + f" – első valódi hiány: {first['start']:%Y-%m-%d %H:%M} ({first['kind']})")
            elif lag > MAX_LAG_BARS[tf]:
                res.fail(msg + f" – elavult, {lag} gyertya késés")
            else:
                res.ok(msg)


def check_funding(cfg: Config, res: CheckResult) -> None:
    res.lines.append("Funding (Binance):")
    for sym in symbols(cfg):
        df = store.read_funding(cfg, sym)
        if df.empty:
            res.fail(f"{sym}: nincs funding")
            continue
        # rés: két esemény között több mint másfélszeres intervallum
        gap_h = df["ts"].diff().iloc[1:] / 3_600_000
        allowed = df["funding_interval_hours"].iloc[1:] * 1.5
        n_gaps = int((gap_h > allowed).sum())
        msg = f"{sym}: {len(df)} esemény, {_fmt(df['ts'].min())} – {_fmt(df['ts'].max())}, rés: {n_gaps}"
        (res.fail if n_gaps else res.ok)(msg)


def check_metrics(cfg: Config, res: CheckResult) -> None:
    res.lines.append("Open interest (Binance metrics, tájékoztató):")
    for sym in symbols(cfg):
        df = store.read_metrics(cfg, sym)
        if df.empty:
            res.fail(f"{sym}: nincs OI")
            continue
        days = pd.to_datetime(df["ts"], unit="ms", utc=True).dt.normalize().nunique()
        res.ok(f"{sym}: {len(df)} sor, {days} nap, {_fmt(df['ts'].min())} – {_fmt(df['ts'].max())}")


def check_checksums(cfg: Config, res: CheckResult) -> None:
    res.lines.append("Checksum (a gyorsítótár minden zipje):")
    zips = sorted(store.raw_dir(cfg).rglob("*.zip"))
    bad = [z for z in zips if not verify_cached(z)]
    if not zips:
        res.fail("nincs letöltött zip")
    elif bad:
        res.fail(f"{len(bad)}/{len(zips)} zip checksumja rossz, pl. {bad[0].name}")
    else:
        res.ok(f"{len(zips)}/{len(zips)} zip checksum OK")


def check_regime(cfg: Config, res: CheckResult) -> None:
    res.lines.append("Rezsimcímkék (regime_daily):")
    if not cfg.db_path.exists():
        res.fail("nincs adatbázis")
        return
    with connect(cfg.db_path) as conn:
        rows = {r["symbol"]: r for r in conn.execute(
            "SELECT symbol, COUNT(*) n, MIN(date) a, MAX(date) b FROM regime_daily GROUP BY symbol")}
        total = conn.execute("SELECT COUNT(*) FROM regime_daily").fetchone()[0]
        dist = {axis: conn.execute(
            f"SELECT {axis} v, COUNT(*) n FROM regime_daily GROUP BY {axis} ORDER BY n DESC").fetchall()
            for axis in ("trend", "vol", "positioning")}
        combos = conn.execute("SELECT COUNT(DISTINCT trend || '/' || vol) FROM regime_daily").fetchone()[0]
    for sym in symbols(cfg):
        r = rows.get(sym)
        if not r:
            res.fail(f"{sym}: nincs címke")
        else:
            res.ok(f"{sym}: {r['n']} nap, {r['a']} – {r['b']}")
    res.lines.append(f"  összesen {total} sor")
    for axis, vals in dist.items():
        parts = ", ".join(f"{v['v']} {v['n']} ({100 * v['n'] / total:.0f}%)" for v in vals) if total else "-"
        res.lines.append(f"  {axis:<12}: {parts}")
    res.lines.append(f"  trend×vol kombinációk az adatban: {combos}/9")


def check_recorder(cfg: Config, res: CheckResult, hours: int = 24, now: int | None = None) -> None:
    """Az elmúlt 24 óra perceinek hány %-ára van pillanatkép. Elvárás: fut ≥24 órája, ≥95%."""
    from evolab.live.recorder import health

    res.lines.append(f"Hyperliquid rögzítő (utolsó {hours} óra, percek aránya):")
    for sym, h in health(cfg, hours, now).items():
        msg = (f"{sym:<9}: {h['ticks']}/{h['expected']} perc = {100 * h['coverage']:.1f}%, "
               f"legnagyobb rés {h['max_gap_min']:.0f} perc, fut {h['running_hours']:.1f} órája")
        good = h["running_hours"] >= hours and h["coverage"] >= 0.95
        (res.ok if good else res.fail)(msg)


def run_all(cfg: Config, recorder: bool = True) -> CheckResult:
    res = CheckResult()
    check_bars(cfg, res)
    check_funding(cfg, res)
    check_metrics(cfg, res)
    check_checksums(cfg, res)
    check_regime(cfg, res)
    if recorder:
        check_recorder(cfg, res)
    return res

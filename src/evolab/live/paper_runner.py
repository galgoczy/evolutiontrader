"""Élő paper-könyvelés Hyperliquid-adaton (docs/02-specifikacio.md 4., 5. fázis).

Egy kód, két mód: a paper ugyanazzal a `sim.engine.run`-nal fut, mint a visszateszt, csak a bemenet
a rögzítő Hyperliquid-gyertyái (`store.load_hl_barframe`), és a futás a stratégia paper-kezdetétől
indul. A jel a teljes Hyperliquid-történeten számolódik (bemelegedés), a könyvelés a kezdettől.
Minden futás determinisztikus újrajátszás: a lezárt gyertyák alapján pontosan azt adja, amit egy
gyertyánként élőben könyvelő folyamat adott volna (a jel kauzális, a motor determinisztikus).

Névsor (`data/paper/roster.json`):
- `L2`: a létrán L2+ szintű (emberi jóváhagyással előléptetett) stratégiák;
- `shadow`: árnyék-paper (felhasználói döntés, 2026-10-12): amíg nincs L2-es egyed, a legjobb
  DSR-ű `paper.shadow_top_n` variáns fut mérésre (paper = visszateszt egyezés, valódi slippage).
  Az árnyék nem lép szintet és nem kerül a jóváhagyási listára.
A STOP kapcsoló leállítja a paper-könyvelést (a rögzítő fut tovább).
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pandas as pd

from evolab import backtest
from evolab.config import Config
from evolab.data import store
from evolab.data.universe import now_ms, symbols, tf_ms
from evolab.db import connect, init_db
from evolab.sim import engine
from evolab.sim.costs import Costs
from evolab.sim.risk import RiskParams
from evolab.strategy import registry
from evolab.strategy.base import align_regime

L2_LEVELS = ("L2", "L3", "L4")


def paper_dir(cfg: Config) -> Path:
    return store.data_dir(cfg) / "paper"


def roster_path(cfg: Config) -> Path:
    return paper_dir(cfg) / "roster.json"


def read_roster(cfg: Config) -> dict:
    p = roster_path(cfg)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"strategies": {}}


def write_roster(cfg: Config, roster: dict) -> None:
    p = roster_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(roster, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def shadow_candidates(cfg: Config, n: int) -> list[str]:
    """A legutolsó L1-ítéletek közül a legjobb DSR-ű `n` variáns (döntetlennél azonosító szerint)."""
    from evolab.evolve.population import latest_verdicts

    v = latest_verdicts(cfg)
    if v.empty:
        return []
    known = set(registry.discover())
    v = v[v["strategy_id"].isin(known)].sort_values(["dsr", "strategy_id"], ascending=[False, True])
    return v["strategy_id"].head(n).tolist()


def l2_strategies(cfg: Config) -> list[str]:
    if not cfg.db_path.exists():
        return []
    with connect(cfg.db_path) as conn:
        rows = conn.execute(f"SELECT strategy_id FROM strategies WHERE level IN ({','.join('?' * len(L2_LEVELS))})",
                            L2_LEVELS).fetchall()
    return [r["strategy_id"] for r in rows]


def ensure_roster(cfg: Config, now: int | None = None, reselect_shadow: bool = False) -> dict:
    """A névsor létrehozása / kiegészítése. Az árnyék-lista rögzül (nem választódik újra minden futáskor),
    hogy a paper-történetek folytonosak legyenek; `reselect_shadow` új listát választ."""
    now = now if now is not None else now_ms()
    start = now // tf_ms("4h") * tf_ms("4h")  # az aktuális 4 órás gyertya nyitása
    added = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    roster = read_roster(cfg)
    strategies = roster["strategies"]
    if reselect_shadow:
        strategies = {k: v for k, v in strategies.items() if v["mode"] != "shadow"}
    current_l2 = set(l2_strategies(cfg))
    for sid in current_l2:
        if strategies.get(sid, {}).get("mode") != "L2":
            strategies[sid] = {"mode": "L2", "start_ms": start, "added": added}
    for sid in [k for k, v in strategies.items() if v["mode"] == "L2" and k not in current_l2]:
        roster.setdefault("ended", {})[sid] = {**strategies.pop(sid), "ended": added}  # visszaléptetve
    if not any(v["mode"] == "shadow" for v in strategies.values()):
        for sid in shadow_candidates(cfg, int(cfg.lab["paper"]["shadow_top_n"])):
            strategies.setdefault(sid, {"mode": "shadow", "start_ms": start, "added": added})
    roster["strategies"] = strategies
    write_roster(cfg, roster)
    return roster


def simulate(cfg: Config, sid: str, start_ms: int, bars: pd.DataFrame, regime: pd.DataFrame,
             mode: str = "paper") -> engine.Result:
    """Jel a teljes soron, könyvelés `start_ms`-től, a végén nyitva maradó pozíciókkal."""
    strat = registry.load(sid)
    sig = strat.signals(bars, regime)
    win = bars.index.get_level_values("ts") >= start_ms
    return engine.run(bars[win], sig[win], strat.meta.timeframe, Costs.from_config(cfg.lab["costs"]),
                      RiskParams.from_config(cfg.lab["risk"]), regime=regime[win], mode=mode, close_at_end=False)


def _inputs(cfg: Config, tf: str, venue: str, cache: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    key = (venue, tf)
    if key not in cache:
        syms = symbols(cfg)
        bars = store.load_hl_barframe(cfg, syms, tf) if venue == "hl" else store.load_barframe(cfg, syms, tf)
        cache[key] = (bars, align_regime(backtest.read_regime(cfg, syms), bars.index))
    return cache[key]


def run(cfg: Config, sync: bool = True, log=print) -> dict:
    """Egy paper-kör: Hyperliquid-gyertyák szinkronja, majd minden névsorbeli stratégia újrajátszása."""
    if cfg.stop_file.exists():
        log("STOP kapcsoló aktív: paper-könyvelés kihagyva.")
        return {}
    if sync:
        from evolab.data.hyperliquid_live import HLInfo
        from evolab.live.recorder import sync_candles

        sync_candles(cfg, HLInfo(cfg.lab["sources"]["hyperliquid_info"], min_interval=1.0))
    roster = ensure_roster(cfg)
    cache: dict = {}
    out = {}
    for sid, info in sorted(roster["strategies"].items()):
        try:
            tf = registry.load(sid).meta.timeframe
            bars, regime = _inputs(cfg, tf, "hl", cache)
            res = simulate(cfg, sid, info["start_ms"], bars, regime)
            out[sid] = _write(cfg, sid, info, res)
        except Exception as e:  # egy stratégia hibája ne állítsa le a többit
            out[sid] = {"error": f"{type(e).__name__}: {e}"}
        log(f"  {sid:<34} {info['mode']:<6} {_line(out[sid])}")
    _log_run(cfg, out)
    return out


def _line(s: dict) -> str:
    if "error" in s:
        return f"HIBA {s['error']}"
    return (f"gyertya {s['bars']:>4}, kötés {s['trades']:>3}, nyitott {s['open_positions']}, "
            f"hozam {s['return_pct']:+.2f}%")


def _write(cfg: Config, sid: str, info: dict, res: engine.Result) -> dict:
    d = paper_dir(cfg) / sid
    for name, df in (("trades", res.trades), ("equity", res.equity), ("open_positions", res.open_positions),
                     ("events", res.events)):
        store.write_parquet(df, d / f"{name}.parquet")
    eq = res.equity["equity"]
    summary = {"strategy_id": sid, "mode": info["mode"], "start_ms": info["start_ms"],
               "bars": int(len(eq)), "trades": int(len(res.trades)), "open_positions": int(len(res.open_positions)),
               "equity": float(eq.iloc[-1]) if len(eq) else res.initial_capital,
               "return_pct": float(100 * (eq.iloc[-1] / res.initial_capital - 1)) if len(eq) else 0.0,
               "max_dd_pct": float(100 * (1 - eq / eq.cummax()).max()) if len(eq) else 0.0,
               "last_bar_close": int(res.equity["ts"].iloc[-1]) if len(eq) else None, "status": res.status}
    (d / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def _log_run(cfg: Config, out: dict) -> None:
    init_db(cfg)
    errors = [k for k, v in out.items() if "error" in v]
    with connect(cfg.db_path) as conn:
        conn.execute("INSERT INTO runs(kind, step, status, message, finished_at) "
                     "VALUES ('paper', 'run', ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ','now'))",
                     ("error" if errors else "ok", f"{len(out)} stratégia, hibás: {', '.join(errors) or '-'}"))


def read_summary(cfg: Config, sid: str) -> dict | None:
    p = paper_dir(cfg) / sid / "summary.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


# ---------------------------------------------------------------- paper = visszateszt egyezés


def compare(cfg: Config, sid: str, cache: dict | None = None) -> dict:
    """Ugyanarra az időszakra (a paper kezdetétől a két adatsor közös végéig) a Hyperliquid-paper és a
    Binance-visszateszt equity-je. Elfogadás (spec 4., 10.): a végső equity-k eltérése <= `paper.match_tolerance_pct`.

    Ez konzisztencia-ellenőrzés, nem értékelés: nem ír a ledgerbe és nem befolyásol kaput, ezért
    olvashatja a holdout-ablakba eső friss Binance-adatot.
    """
    cache = cache if cache is not None else {}
    info = read_roster(cfg)["strategies"][sid]
    tf = registry.load(sid).meta.timeframe
    hl_b, hl_r = _inputs(cfg, tf, "hl", cache)
    bn_b, bn_r = _inputs(cfg, tf, "binance", cache)
    end = min(int(hl_b.index.get_level_values("ts").max()), int(bn_b.index.get_level_values("ts").max()))
    hl_b, hl_r = hl_b[hl_b.index.get_level_values("ts") <= end], hl_r[hl_r.index.get_level_values("ts") <= end]
    bn_b, bn_r = bn_b[bn_b.index.get_level_values("ts") <= end], bn_r[bn_r.index.get_level_values("ts") <= end]
    paper = simulate(cfg, sid, info["start_ms"], hl_b, hl_r)
    bt = simulate(cfg, sid, info["start_ms"], bn_b, bn_r, mode="backtest")
    if paper.equity.empty or bt.equity.empty:
        return {"strategy_id": sid, "days": 0.0, "diff_pct": None, "ok": None}
    pe, be = float(paper.equity["equity"].iloc[-1]), float(bt.equity["equity"].iloc[-1])
    days = (end + tf_ms(tf) - info["start_ms"]) / 86_400_000
    diff = 100 * abs(pe - be) / be
    tol = float(cfg.lab["paper"]["match_tolerance_pct"])
    return {"strategy_id": sid, "days": round(days, 2), "paper_equity": pe, "backtest_equity": be,
            "diff_pct": diff, "ok": diff <= tol, "tolerance_pct": tol,
            "paper_trades": int(len(paper.trades)), "backtest_trades": int(len(bt.trades)),
            "final_check": days >= float(cfg.lab["paper"]["compare_min_days"])}


# ---------------------------------------------------------------- valódi slippage


def measured_slippage(cfg: Config, days: int = 7, now: int | None = None) -> pd.DataFrame:
    """A Hyperliquid impact-árából mért fél-szórás (a mid-től) az utolsó `days` napban, coinonként,
    a modell (`costs`) 4h-s becslésével összevetve. A modell: slippage_base + mult × ATR/ár."""
    from evolab.features.indicators import atr

    now = now if now is not None else now_ms()
    c = cfg.lab["costs"]
    rows = []
    for sym in symbols(cfg):
        t = store.read_hl_ticks(cfg, sym)
        if "impact_ask" in t:
            t = t[(t["ts"] >= now - days * 86_400_000) & t["impact_ask"].notna()]
        else:
            t = t.iloc[0:0]
        bars = store.read_bars(cfg, sym, "4h")
        model = None
        if not bars.empty:
            a = atr(bars.tail(200), 14).iloc[-1]
            model = 100 * (float(c["slippage_base"]) + float(c["slippage_atr_mult"]) * a / bars["close"].iloc[-1])
        if t.empty:
            rows.append({"symbol": sym, "samples": 0, "measured_pct": None, "model_pct": model})
            continue
        half = pd.concat([(t["impact_ask"] - t["mid_px"]) / t["mid_px"], (t["mid_px"] - t["impact_bid"]) / t["mid_px"]])
        rows.append({"symbol": sym, "samples": int(len(t)), "measured_pct": float(100 * half.median()),
                     "measured_p95_pct": float(100 * half.quantile(0.95)), "model_pct": model})
    return pd.DataFrame(rows)

"""Hyperliquid élő rögzítő (spec 2.3). Az első naptól fut, a STOP kapcsoló nem állítja le.

- percenként: minden univerzum-coin mark/mid/oracle ára, OI-ja, fundingja
  -> pufferként data/hl/buffer/ticks_<YYYY-MM-DD>.jsonl (UTC nap, soronként egy coin)
- óránként: a puffer tömörítése data/hl/<symbol>/ticks_<YYYY-MM-DD>.parquet-be;
  a lezárt nap JSONL-je a sikeres tömörítés után törlődik
- 4 óránként: lezárt 1h/4h gyertyák és a funding-történet
  -> data/hl/<symbol>/candles_<tf>.parquet, funding.parquet
"""

from __future__ import annotations

import datetime as dt
import json
import threading
import time
import traceback
from pathlib import Path

import pandas as pd

from evolab.config import Config
from evolab.data import store
from evolab.data.hyperliquid_live import HLInfo
from evolab.data.universe import hl_coin, last_closed_open_ms, now_ms, symbols, tf_ms

CANDLE_TFS = ("1h", "4h")
CANDLE_SYNC_MS = 4 * 3_600_000
COMPACT_MS = 3_600_000
HL_HISTORY_START_MS = int(pd.Timestamp("2023-01-01", tz="UTC").timestamp() * 1000)


def _day(ts_ms: int) -> str:
    return dt.datetime.fromtimestamp(ts_ms / 1000, dt.UTC).strftime("%Y-%m-%d")


def buffer_dir(cfg: Config) -> Path:
    return store.data_dir(cfg) / "hl" / "buffer"


def buffer_path(cfg: Config, ts_ms: int) -> Path:
    return buffer_dir(cfg) / f"ticks_{_day(ts_ms)}.jsonl"


def tick_path(cfg: Config, symbol: str, ts_ms: int) -> Path:
    return store.hl_dir(cfg, symbol) / f"ticks_{_day(ts_ms)}.parquet"


def _append(path, new: pd.DataFrame) -> pd.DataFrame:
    old = store.read_parquet(path)
    df = pd.concat([old, new], ignore_index=True) if not old.empty else new
    df = df.drop_duplicates("ts", keep="last").sort_values("ts").reset_index(drop=True)
    store.write_parquet(df, path)
    return df


def record_ticks(cfg: Config, hl: HLInfo, ts_ms: int | None = None) -> int:
    """Egy pillanatkép hozzáfűzése a napi JSONL-pufferhez. `ts` a perc eleje, `recv_ts` a fogadás."""
    recv = now_ms()
    ts = ts_ms if ts_ms is not None else (recv // 60_000) * 60_000
    by_coin = {hl_coin(s): s for s in symbols(cfg)}
    snap = hl.asset_ctxs(list(by_coin))
    path = buffer_path(cfg, ts)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for row in snap.to_dict("records"):
        row["symbol"] = by_coin[row.pop("coin")]
        lines.append(json.dumps({"ts": ts, "recv_ts": recv, **row}))
    with path.open("a", encoding="utf-8") as f:
        f.write("".join(line + "\n" for line in lines))
    return len(lines)


def _read_jsonl(path: Path) -> pd.DataFrame:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:  # félbeszakadt utolsó sor (pl. áramszünet)
                continue
    return pd.DataFrame(rows)


def compact(cfg: Config, now: int | None = None) -> int:
    """JSONL-puffer -> napi parquet coinonként. Lezárt nap pufferét utána törli. Idempotens."""
    today = _day(now if now is not None else now_ms())
    n = 0
    for path in sorted(buffer_dir(cfg).glob("ticks_*.jsonl")):
        day = path.stem.removeprefix("ticks_")
        df = _read_jsonl(path)
        if not df.empty:
            for sym, part in df.groupby("symbol"):
                ts0 = int(part["ts"].iloc[0])
                _append(tick_path(cfg, sym, ts0), part.drop(columns="symbol").reset_index(drop=True))
            n += len(df)
        if day < today:
            path.unlink()
    return n


def sync_candles(cfg: Config, hl: HLInfo) -> None:
    """Lezárt gyertyák és funding pótlása az utolsó mentett időponttól."""
    for sym in symbols(cfg):
        coin = hl_coin(sym)
        for tf in CANDLE_TFS:
            path = store.hl_dir(cfg, sym) / f"candles_{tf}.parquet"
            old = store.read_parquet(path)
            start = int(old["ts"].max()) + tf_ms(tf) if not old.empty else HL_HISTORY_START_MS
            until = last_closed_open_ms(tf)
            frames = []
            while start <= until:
                df = hl.candles(coin, tf, start, until + tf_ms(tf) - 1)
                df = df[df["ts"] <= until] if not df.empty else df
                if df.empty:
                    break
                frames.append(df)
                start = int(df["ts"].max()) + tf_ms(tf)
            if frames:
                _append(path, pd.concat(frames, ignore_index=True))
        path = store.hl_dir(cfg, sym) / "funding.parquet"
        old = store.read_parquet(path)
        start = int(old["ts"].max()) + 1 if not old.empty else HL_HISTORY_START_MS
        while True:
            df = hl.funding_history(coin, start)
            if df.empty:
                break
            _append(path, df)
            if len(df) < 500:
                break
            start = int(df["ts"].max()) + 1


def _stamp() -> str:
    return f"{dt.datetime.now():%F %T}"


def _sync_job(cfg: Config, hl: HLInfo, log) -> None:
    try:
        sync_candles(cfg, hl)
        log(f"{_stamp()} gyertyák szinkronizálva")
    except Exception as e:
        log(f"{_stamp()} gyertya hiba: {type(e).__name__}: {e}")


def run(cfg: Config, hl: HLInfo | None = None, max_loops: int | None = None, log=print) -> None:
    """Végtelen hurok (launchd KeepAlive tartja életben). Bármely hibánál naplóz és megy tovább.

    A gyertya-szinkron külön szálon, lassított kérésekkel fut, hogy az első (hosszú) pótlás
    alatt se maradjon ki percenkénti pillanatkép.
    """
    url = cfg.lab["sources"]["hyperliquid_info"]
    hl_sync = hl or HLInfo(url, min_interval=3.0)  # tesztben a megadott (ál)klienst használja
    hl = hl or HLInfo(url)
    sync_thread: threading.Thread | None = None
    last_sync = last_compact = 0
    loops = errors = 0
    log(f"{_stamp()} rögzítő indul: {', '.join(symbols(cfg))}")
    while max_loops is None or loops < max_loops:
        loops += 1
        try:
            record_ticks(cfg, hl)
            if errors:
                log(f"{_stamp()} tick ismét OK ({errors} hibás perc után)")
            errors = 0
        except Exception as e:
            errors += 1
            if errors <= 3 or errors % 60 == 0:  # tartós hibánál ne teljen meg a napló
                log(f"{_stamp()} tick hiba #{errors}: {type(e).__name__}: {e}")
        if now_ms() - last_compact >= COMPACT_MS:
            try:
                n = compact(cfg)
                last_compact = now_ms()
                log(f"{_stamp()} tömörítés: {n} puffer-sor -> parquet")
            except Exception:
                log(f"{_stamp()} tömörítési hiba:\n{traceback.format_exc()}")
        if now_ms() - last_sync >= CANDLE_SYNC_MS and not (sync_thread and sync_thread.is_alive()):
            last_sync = now_ms()
            sync_thread = threading.Thread(target=_sync_job, args=(cfg, hl_sync, log), daemon=True)
            sync_thread.start()
        if max_loops is None or loops < max_loops:
            time.sleep(60 - (time.time() % 60) + 1)  # a következő perc eleje után 1 mp


def _ticks(cfg: Config, symbol: str, since: int, until: int) -> pd.Series:
    """Az adott coin tick-időbélyegei parquetből és a még nem tömörített pufferből."""
    days = sorted({_day(t) for t in range(since, until + 86_400_000, 86_400_000)})
    parts = []
    for d in days:
        pq = store.hl_dir(cfg, symbol) / f"ticks_{d}.parquet"
        if pq.exists():
            parts.append(pd.read_parquet(pq, columns=["ts"])["ts"])
        buf = buffer_dir(cfg) / f"ticks_{d}.jsonl"
        if buf.exists():
            df = _read_jsonl(buf)
            if not df.empty:
                parts.append(df.loc[df["symbol"] == symbol, "ts"])
    if not parts:
        return pd.Series(dtype="int64")
    ts = pd.concat(parts, ignore_index=True).astype("int64").drop_duplicates()
    return ts[(ts >= since) & (ts < until)].sort_values()


def health(cfg: Config, hours: int = 24, now: int | None = None) -> dict[str, dict]:
    """Rögzítő-lefedettség coinonként az utolsó `hours` órára: tickszám/percszám, legnagyobb rés."""
    now = now if now is not None else now_ms()
    until = (now // 60_000) * 60_000
    since = until - hours * 3_600_000
    out = {}
    for sym in symbols(cfg):
        ts = _ticks(cfg, sym, since, until)
        edges = pd.concat([pd.Series([since - 60_000]), ts, pd.Series([until])], ignore_index=True)
        first = _first_tick(cfg, sym)
        out[sym] = {
            "ticks": int(len(ts)),
            "expected": hours * 60,
            "coverage": len(ts) / (hours * 60),
            "max_gap_min": float(edges.diff().max() / 60_000) - 1,
            "running_hours": (now - first) / 3_600_000 if first else 0.0,
        }
    return out


def _first_tick(cfg: Config, symbol: str) -> int | None:
    files = sorted(store.hl_dir(cfg, symbol).glob("ticks_*.parquet"))
    if files:
        return int(pd.read_parquet(files[0], columns=["ts"])["ts"].min())
    bufs = sorted(buffer_dir(cfg).glob("ticks_*.jsonl"))
    for b in bufs:
        df = _read_jsonl(b)
        if not df.empty and (df["symbol"] == symbol).any():
            return int(df.loc[df["symbol"] == symbol, "ts"].min())
    return None

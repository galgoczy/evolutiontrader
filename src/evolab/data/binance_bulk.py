"""Binance USDT-M történelmi adat: data.binance.vision bulk + CCXT a legutolsó órákra (spec 2.2).

Menet sorozatonként (fajta × coin × idősík):
1. a tárhely listájából kiderül, mely havi és napi zip létezik (nincs 404-próbálgatás),
2. havi zip minden hónapra `history_start`-tól; ahol nincs havi, ott a napi zipek,
3. minden zip a `.CHECKSUM` fájl SHA-256-jával ellenőrizve, csak ellenőrzött zip kerül a
   gyorsítótárba (data/raw/binance/...),
4. a bulk utolsó gyertyája után CCXT-vel (binanceusdm nyers végpontok) az utolsó lezárt gyertyáig,
5. a parquet a gyorsítótárból újraépül (idempotens; ha nincs új zip, nem nyúl hozzá).
"""

from __future__ import annotations

import hashlib
import io
import re
import xml.etree.ElementTree as ET
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pandas as pd

from evolab.config import Config
from evolab.data import store
from evolab.data.universe import (
    history_start,
    last_closed_open_ms,
    symbols,
    tf_ms,
    timeframes,
    to_ms,
)

LIST_URL = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
PREFIX = "data/futures/um"
KLINE_KINDS = ("klines", "markPriceKlines", "premiumIndexKlines")
WORKERS = 8
_S3_NS = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
_DATE_RE = re.compile(r"-(\d{4}-\d{2})(-\d{2})?\.zip$")


class ChecksumError(RuntimeError):
    pass


@dataclass
class UpdateReport:
    downloaded: int = 0
    cached: int = 0
    api_filled: int = 0
    rebuilt: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        s = (f"új zip: {self.downloaded}, gyorsítótárból: {self.cached}, újraépítve: {len(self.rebuilt)}, "
             f"API-ból pótolt gyertya: {self.api_filled}")
        if self.errors:
            s += f", HIBÁK: {len(self.errors)}"
        return s


# ---------------------------------------------------------------- tárhely-lista


def list_keys(client: httpx.Client, prefix: str, marker: str = "") -> list[str]:
    """A tárhely kulcsai (csak .zip) a prefix alatt, lapozva. `marker` után kezd."""
    keys: list[str] = []
    while True:
        r = client.get(LIST_URL, params={"prefix": prefix, "marker": marker})
        r.raise_for_status()
        root = ET.fromstring(r.content)
        page = [k.text for k in root.iterfind("s3:Contents/s3:Key", _S3_NS) if k.text]
        keys += [k for k in page if k.endswith(".zip")]
        if root.findtext("s3:IsTruncated", default="false", namespaces=_S3_NS) != "true" or not page:
            return keys
        marker = page[-1]


def _period(key: str) -> str:
    """'...-2024-03.zip' -> '2024-03', '...-2024-03-05.zip' -> '2024-03-05'."""
    m = _DATE_RE.search(key)
    if not m:
        raise ValueError(f"Nem értelmezhető fájlnév: {key}")
    return m.group(1) + (m.group(2) or "")


def plan_files(monthly: list[str], daily: list[str], start: pd.Timestamp) -> list[str]:
    """Havi zip, ahol van; a havi által le nem fedett napokra napi zip. Csak `start`-tól."""
    start_month, start_day = start.strftime("%Y-%m"), start.strftime("%Y-%m-%d")
    months = {_period(k): k for k in monthly if _period(k) >= start_month}
    days = {
        _period(k): k
        for k in daily
        if _period(k) >= start_day and _period(k)[:7] not in months
    }
    return [months[p] for p in sorted(months)] + [days[p] for p in sorted(days)]


def _series_prefix(kind: str, period: str, symbol: str, tf: str | None) -> str:
    return f"{PREFIX}/{period}/{kind}/{symbol}/" + (f"{tf}/" if tf else "")


def discover(client: httpx.Client, kind: str, symbol: str, tf: str | None, start: pd.Timestamp) -> list[str]:
    """A sorozat felhasználandó zip-kulcsai."""
    monthly = [] if kind == "metrics" else list_keys(client, _series_prefix(kind, "monthly", symbol, tf))
    if kind == "fundingRate":  # funding csak havi fájlban van; a friss rész CCXT-ből jön
        return plan_files(monthly, [], start)
    # A napi listát csak az első le nem fedett hónaptól kérjük (különben évekig lapozna).
    months = sorted(_period(k) for k in monthly)
    marker = ""
    if months:
        have = set(months)
        rng = pd.period_range(months[0], pd.Timestamp.now(tz="UTC").strftime("%Y-%m"), freq="M")
        first_hole = next(str(p) for p in rng if str(p) not in have)
        name = f"{symbol}-{tf}" if tf else f"{symbol}-{kind}"
        marker = _series_prefix(kind, "daily", symbol, tf) + f"{name}-{first_hole}"
    daily = list_keys(client, _series_prefix(kind, "daily", symbol, tf), marker=marker)
    return plan_files(monthly, daily, start)


# ---------------------------------------------------------------- letöltés + checksum


def local_path(cfg: Config, key: str) -> Path:
    return store.raw_dir(cfg) / key.removeprefix(PREFIX + "/")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch(client: httpx.Client, base_url: str, key: str, dest: Path) -> bool:
    """Letölti a zipet és a .CHECKSUM-ot, ellenőriz, atomian ment. True, ha új letöltés volt."""
    if dest.exists():
        return False
    rel = key.removeprefix(PREFIX + "/")
    for attempt in (1, 2):
        data = client.get(f"{base_url}/{rel}").raise_for_status().content
        expected = client.get(f"{base_url}/{rel}.CHECKSUM").raise_for_status().text.split()[0]
        if sha256(data) == expected:
            break
        if attempt == 2:
            raise ChecksumError(f"checksum hiba kétszer: {rel}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(dest)
    Path(str(dest) + ".CHECKSUM").write_text(f"{expected}  {dest.name}\n")
    return True


def verify_cached(path: Path) -> bool:
    """A gyorsítótárban lévő zip egyezik-e a mellette tárolt Binance-checksummal."""
    cs = Path(str(path) + ".CHECKSUM")
    return cs.exists() and sha256(path.read_bytes()) == cs.read_text().split()[0]


# ---------------------------------------------------------------- feldolgozás


def _read_csv(path: Path) -> pd.DataFrame:
    """A zipben lévő CSV beolvasása; a fejléc néhol van, néhol nincs."""
    with zipfile.ZipFile(path) as z:
        raw = z.read(z.namelist()[0])
    df = pd.read_csv(io.BytesIO(raw), header=None, dtype=str)
    first = df.iloc[0, 0] if len(df) else ""
    if len(df) and not str(first).replace("-", "").replace(" ", "").replace(":", "").isdigit():
        df = df.iloc[1:]  # fejlécsor
    return df.reset_index(drop=True)


def parse_klines(path: Path) -> pd.DataFrame:
    df = _read_csv(path)
    out = pd.DataFrame({"ts": to_ms(df[0])})
    for i, col in enumerate(["open", "high", "low", "close", "volume"], start=1):
        out[col] = pd.to_numeric(df[i])
    out["quote_volume"] = pd.to_numeric(df[7])
    out["trades"] = pd.to_numeric(df[8]).astype("int64")
    return out


def parse_funding(path: Path) -> pd.DataFrame:
    df = _read_csv(path)
    return pd.DataFrame({
        "ts": to_ms(df[0]),
        "funding_rate": pd.to_numeric(df[2]),
        "funding_interval_hours": pd.to_numeric(df[1]).astype("int64"),
    })


def parse_metrics(path: Path) -> pd.DataFrame:
    df = _read_csv(path)
    ts = pd.to_datetime(df[0], utc=True).astype("int64") // 10**6
    return pd.DataFrame({
        "ts": ts.astype("int64"),
        "oi": pd.to_numeric(df[2]),
        "oi_value": pd.to_numeric(df[3]),
    })


def _concat(frames: list[pd.DataFrame]) -> pd.DataFrame:
    frames = [f for f in frames if not f.empty]
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    # utolsó nyer: a bulk után jövő CCXT-sor csak a bulk vége utáni gyertyákat tölti
    return df.drop_duplicates("ts", keep="last").sort_values("ts").reset_index(drop=True)


def build_bars(kline: pd.DataFrame, mark: pd.DataFrame, premium: pd.DataFrame) -> pd.DataFrame:
    """Az utolsó lezárt gyertyáig: OHLCV + mark_close + premium_close egy táblában."""
    df = kline.copy()
    for src, col in ((mark, "mark_close"), (premium, "premium_close")):
        s = src.set_index("ts")["close"] if not src.empty else pd.Series(dtype=float)
        df[col] = df["ts"].map(s)
    return df[store.BAR_COLUMNS]


# ---------------------------------------------------------------- CCXT-farok


def _exchange():
    import ccxt  # lassú import, csak ha kell

    return ccxt.binanceusdm({"enableRateLimit": True})


_TAIL_ENDPOINTS = {
    "klines": "fapiPublicGetKlines",
    "markPriceKlines": "fapiPublicGetMarkPriceKlines",
    "premiumIndexKlines": "fapiPublicGetPremiumIndexKlines",
}


def ccxt_tail(ex, kind: str, symbol: str, tf: str, after_ms: int, until_ms: int) -> pd.DataFrame:
    """Gyertyák `after_ms` után az utolsó lezárt gyertyáig, ugyanabban a sémában, mint a bulk."""
    rows: list[list] = []
    start = after_ms + tf_ms(tf)
    method = getattr(ex, _TAIL_ENDPOINTS[kind])
    while start <= until_ms:
        batch = method({"symbol": symbol, "interval": tf, "startTime": start,
                        "endTime": until_ms, "limit": 1500})
        if not batch:
            break
        rows += batch
        start = int(batch[-1][0]) + tf_ms(tf)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    out = pd.DataFrame({"ts": to_ms(df[0])})
    for i, col in enumerate(["open", "high", "low", "close", "volume"], start=1):
        out[col] = pd.to_numeric(df[i])
    out["quote_volume"] = pd.to_numeric(df[7])
    out["trades"] = pd.to_numeric(df[8]).astype("int64")
    return out[out["ts"] <= until_ms]


def fill_holes(ex, kind: str, symbol: str, tf: str, df: pd.DataFrame, grid: pd.Index) -> pd.DataFrame:
    """A `grid` gyertyái közül a hiányzókat a REST API-ból pótolja (a havi archívumból néha egész
    napok hiányoznak). Ami az API-ban sincs meg, az valódi hiány marad, és a hiányriport jelzi."""
    have = pd.Index(df["ts"]) if not df.empty else pd.Index([], dtype="int64")
    missing = grid.difference(have)
    if missing.empty:
        return df
    step = tf_ms(tf)
    runs: list[list[int]] = []
    for t in missing:
        if runs and t == runs[-1][1] + step:
            runs[-1][1] = t
        else:
            runs.append([t, t])
    got = [ccxt_tail(ex, kind, symbol, tf, a - step, b) for a, b in runs]
    return _concat([df, *got])


def ccxt_funding_tail(ex, symbol: str, after_ms: int) -> pd.DataFrame:
    rows: list[dict] = []
    start = after_ms + 1
    while True:
        batch = ex.fapiPublicGetFundingRate({"symbol": symbol, "startTime": start, "limit": 1000})
        if not batch:
            break
        rows += batch
        if len(batch) < 1000:
            break
        start = int(batch[-1]["fundingTime"]) + 1
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    interval = 8  # a nyers végpont nem adja; az utolsó ismert bulk-értéket a hívó írja felül
    return pd.DataFrame({
        "ts": to_ms(df["fundingTime"]),
        "funding_rate": pd.to_numeric(df["fundingRate"]),
        "funding_interval_hours": interval,
    })


# ---------------------------------------------------------------- fő belépési pont


def _download_all(cfg: Config, client: httpx.Client, keys: list[str], report: UpdateReport) -> set[str]:
    """Párhuzamos letöltés. Visszaadja az újonnan letöltött kulcsokat."""
    base = cfg.lab["sources"]["binance_vision"]
    new: set[str] = set()

    def one(key: str) -> tuple[str, bool | Exception]:
        try:
            return key, fetch(client, base, key, local_path(cfg, key))
        except Exception as e:  # egy fájl hibája ne állítsa le a többit
            return key, e

    with ThreadPoolExecutor(WORKERS) as pool:
        for key, res in pool.map(one, keys):
            if isinstance(res, Exception):
                report.errors.append(f"{key}: {res}")
            elif res:
                report.downloaded += 1
                new.add(key)
            else:
                report.cached += 1
    return new


def update(cfg: Config, symbol_list: list[str] | None = None, client: httpx.Client | None = None,
           ex=None, force_rebuild: bool = False, log=print) -> UpdateReport:
    """Letölt, ellenőriz, és újraépíti a parquet fájlokat. Idempotens."""
    report = UpdateReport()
    start = history_start(cfg)
    own_client = client is None
    client = client or httpx.Client(timeout=60, follow_redirects=True)
    ex = ex or _exchange()
    try:
        for symbol in symbol_list or symbols(cfg):
            # 1) mi kell
            plan: dict[tuple[str, str | None], list[str]] = {}
            for tf in timeframes(cfg):
                for kind in KLINE_KINDS:
                    plan[(kind, tf)] = discover(client, kind, symbol, tf, start)
            plan[("fundingRate", None)] = discover(client, "fundingRate", symbol, None, start)
            plan[("metrics", None)] = discover(client, "metrics", symbol, None, start)
            # 2) letöltés
            all_keys = [k for ks in plan.values() for k in ks]
            new = _download_all(cfg, client, all_keys, report)
            log(f"{symbol}: {len(all_keys)} zip, ebből új {len(new)}")
            # 3) újraépítés
            for tf in timeframes(cfg):
                _rebuild_bars(cfg, ex, symbol, tf, plan, new, force_rebuild, report)
            _rebuild_funding(cfg, ex, symbol, plan[("fundingRate", None)], new, force_rebuild, report)
            keys = plan[("metrics", None)]
            path = store.metrics_path(cfg, symbol)
            if force_rebuild or not path.exists() or new.intersection(keys):
                df = _concat([parse_metrics(local_path(cfg, k)) for k in keys])
                store.write_parquet(df, path)
                report.rebuilt.append(f"{symbol}/metrics")
    finally:
        if own_client:
            client.close()
    return report


def _rebuild_bars(cfg, ex, symbol, tf, plan, new, force, report) -> None:
    path = store.bars_path(cfg, symbol, tf)
    until = last_closed_open_ms(tf)
    old = store.read_parquet(path)
    if not force and not old.empty and not any(new.intersection(plan[(k, tf)]) for k in KLINE_KINDS):
        if int(old["ts"].max()) >= until:
            return  # semmi új
    parts = {}
    grid = None
    for kind in KLINE_KINDS:  # a klines az első: annak teljes rácsa a mark/premium rácsa is
        bulk = _concat([parse_klines(local_path(cfg, k)) for k in plan[(kind, tf)]])
        after = int(bulk["ts"].max()) if not bulk.empty else last_closed_open_ms(tf) - 3 * tf_ms(tf)
        tail = ccxt_tail(ex, kind, symbol, tf, after, until)
        df = _concat([bulk, tail])
        if grid is None and not df.empty:
            grid = pd.RangeIndex(int(df["ts"].min()), int(df["ts"].max()) + tf_ms(tf), tf_ms(tf))
        if grid is not None:
            n0 = len(df)
            df = fill_holes(ex, kind, symbol, tf, df, grid)
            report.api_filled += len(df) - n0
        parts[kind] = df
    df = build_bars(parts["klines"], parts["markPriceKlines"], parts["premiumIndexKlines"])
    df = df[df["ts"] >= int(history_start(cfg).timestamp() * 1000)]
    store.write_parquet(df.reset_index(drop=True), path)
    report.rebuilt.append(f"{symbol}/{tf}")


def _rebuild_funding(cfg, ex, symbol, keys, new, force, report) -> None:
    bulk = _concat([parse_funding(local_path(cfg, k)) for k in keys])
    if bulk.empty:
        return
    tail = ccxt_funding_tail(ex, symbol, int(bulk["ts"].max()))
    if not tail.empty:
        tail["funding_interval_hours"] = int(bulk["funding_interval_hours"].iloc[-1])
    store.write_parquet(_concat([bulk, tail]), store.funding_path(cfg, symbol))
    report.rebuilt.append(f"{symbol}/funding")

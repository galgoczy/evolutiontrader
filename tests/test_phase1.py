"""1. fázis: Binance letöltő, hiánykeresés, Hyperliquid rögzítő (hálózat nélkül)."""

import hashlib
import io
import json
import zipfile

import httpx
import pandas as pd
import pytest

from evolab.data import binance_bulk as bb
from evolab.data import gaps, store
from evolab.data.universe import to_ms
from evolab.live import recorder

H = 3_600_000
T0 = int(pd.Timestamp("2024-03-01", tz="UTC").timestamp() * 1000)
KLINE_HEADER = ("open_time,open,high,low,close,volume,close_time,quote_volume,count,"
                "taker_buy_volume,taker_buy_quote_volume,ignore")


def _kline_rows(start_ms: int, n: int, unit: int = 1) -> list[str]:
    rows = []
    for i in range(n):
        t = (start_ms + i * H) * unit
        rows.append(f"{t},100,101,99,100.5,10,{t + H * unit - 1},1005,7,5,502,0")
    return rows


def _zip(path, lines: list[str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(path.stem + ".csv", "\n".join(lines) + "\n")
    path.write_bytes(buf.getvalue())
    return buf.getvalue()


# ---------------------------------------------------------------- időbélyeg és CSV


def test_to_ms_detects_microseconds():
    ms = 1_735_689_600_000  # 2025-01-01
    s = to_ms(pd.Series([ms, ms * 1000, str(ms * 1000)]))
    assert list(s) == [ms, ms, ms]


@pytest.mark.parametrize("header", [False, True])
@pytest.mark.parametrize("unit", [1, 1000])
def test_parse_klines_header_and_unit(tmp_path, header, unit):
    lines = ([KLINE_HEADER] if header else []) + _kline_rows(T0, 3, unit)
    path = tmp_path / "BTCUSDT-1h-2024-03.zip"
    _zip(path, lines)
    df = bb.parse_klines(path)
    assert list(df["ts"]) == [T0, T0 + H, T0 + 2 * H]
    assert df["close"].tolist() == [100.5] * 3
    assert df["trades"].dtype == "int64"


def test_parse_funding_with_header(tmp_path):
    path = tmp_path / "BTCUSDT-fundingRate-2024-03.zip"
    _zip(path, ["calc_time,funding_interval_hours,last_funding_rate", f"{T0},8,0.0001", f"{T0 + 8 * H},8,-0.0002"])
    df = bb.parse_funding(path)
    assert list(df["ts"]) == [T0, T0 + 8 * H]
    assert df["funding_rate"].tolist() == [0.0001, -0.0002]


# ---------------------------------------------------------------- letöltés, checksum, idempotencia


def _transport(files: dict[str, bytes], calls: list[str]):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        name = request.url.path.rsplit("/", 1)[-1]
        if name not in files:
            return httpx.Response(404)
        return httpx.Response(200, content=files[name])
    return httpx.MockTransport(handler)


def test_fetch_verifies_checksum_and_is_idempotent(tmp_path):
    data = _zip(tmp_path / "src.zip", _kline_rows(T0, 2))
    key = f"{bb.PREFIX}/monthly/klines/BTCUSDT/1h/BTCUSDT-1h-2024-03.zip"
    files = {"BTCUSDT-1h-2024-03.zip": data,
             "BTCUSDT-1h-2024-03.zip.CHECKSUM": f"{hashlib.sha256(data).hexdigest()}  x.zip".encode()}
    calls: list[str] = []
    client = httpx.Client(transport=_transport(files, calls))
    dest = tmp_path / "cache" / "BTCUSDT-1h-2024-03.zip"
    assert bb.fetch(client, "https://x", key, dest) is True
    assert bb.verify_cached(dest)
    n = len(calls)
    assert bb.fetch(client, "https://x", key, dest) is False  # újrafuttatás: nincs letöltés
    assert len(calls) == n


def test_fetch_rejects_bad_checksum(tmp_path):
    data = _zip(tmp_path / "src.zip", _kline_rows(T0, 2))
    files = {"a.zip": data, "a.zip.CHECKSUM": b"0" * 64 + b"  a.zip"}
    client = httpx.Client(transport=_transport(files, []))
    dest = tmp_path / "cache" / "a.zip"
    with pytest.raises(bb.ChecksumError):
        bb.fetch(client, "https://x", f"{bb.PREFIX}/a.zip", dest)
    assert not dest.exists()


def test_verify_cached_detects_corruption(tmp_path):
    path = tmp_path / "a.zip"
    data = _zip(path, _kline_rows(T0, 2))
    (tmp_path / "a.zip.CHECKSUM").write_text(hashlib.sha256(data).hexdigest() + "  a.zip\n")
    assert bb.verify_cached(path)
    path.write_bytes(data + b"x")
    assert not bb.verify_cached(path)


def test_plan_files_monthly_then_daily_from_first_available():
    p = "data/futures/um/monthly/klines/SOLUSDT/1h/SOLUSDT-1h-"
    d = "data/futures/um/daily/klines/SOLUSDT/1h/SOLUSDT-1h-"
    monthly = [p + "2020-09.zip", p + "2020-10.zip"]
    daily = [d + "2020-10-31.zip", d + "2020-11-01.zip", d + "2020-11-02.zip"]
    plan = bb.plan_files(monthly, daily, pd.Timestamp("2020-01-01", tz="UTC"))
    # a coin 2020-09-ben indul; a havival lefedett hónap napi fájlja nem kell
    assert plan == [p + "2020-09.zip", p + "2020-10.zip", d + "2020-11-01.zip", d + "2020-11-02.zip"]


# ---------------------------------------------------------------- hiánykeresés


def test_gap_report_separates_known_outages(cfg, tmp_path):
    doc = tmp_path / "DONTESEK.md"
    doc.write_text(
        "# x\n\n## Ismert Binance-leállások\n\n| Kezdet (UTC) | Vég (UTC) | Coinok | Leírás |\n|---|---|---|---|\n"
        "| 2024-03-01 02:00 | 2024-03-01 04:00 | * | karbantartás |\n\n## Más\n"
        "| 2024-03-01 06:00 | 2024-03-01 07:00 | * | ez nem a lista része |\n"
    )
    out = gaps.known_outages(doc)
    assert len(out) == 1
    ts = pd.Series([T0 + i * H for i in range(10) if i not in (2, 3, 6)])
    g = gaps.series_gaps(None, "BTCUSDT", "1h", ts, out)
    assert g[["bars", "kind"]].values.tolist() == [[2, "outage"], [1, "gap"]]
    assert g["start"].iloc[0] == pd.Timestamp("2024-03-01 02:00", tz="UTC")


def test_gap_missing_file_classification(cfg):
    ts = pd.Series([T0, T0 + 3 * H])
    g = gaps.series_gaps(cfg, "BTCUSDT", "1h", ts, gaps.known_outages(cfg.root / "nincs.md"))
    assert g["kind"].tolist() == ["missing_file"]  # nincs zip a gyorsítótárban


def test_repo_outage_list_parses():
    from evolab.config import find_root

    out = gaps.known_outages(find_root() / "docs" / "DONTESEK.md")
    assert (out["end"] > out["start"]).all()


# ---------------------------------------------------------------- Hyperliquid rögzítő


class FakeHL:
    def __init__(self, fail: bool = False):
        self.fail = fail

    def asset_ctxs(self, coins):
        if self.fail:
            raise httpx.ConnectError("nincs hálózat")
        return pd.DataFrame([{"coin": c, "mark_px": 1.0, "mid_px": 1.0, "oracle_px": 1.0,
                              "open_interest": 5.0, "funding": 1e-5, "premium": 0.0,
                              "day_ntl_vlm": 9.0} for c in coins])


def test_recorder_buffers_jsonl_then_compacts(cfg):
    day0 = int(pd.Timestamp("2026-10-09", tz="UTC").timestamp() * 1000)
    for i in range(3):
        assert recorder.record_ticks(cfg, FakeHL(), ts_ms=day0 + i * 60_000) == 6
    buf = recorder.buffer_path(cfg, day0)
    assert len(buf.read_text().splitlines()) == 18
    assert json.loads(buf.read_text().splitlines()[0])["symbol"] == "BTCUSDT"
    # még a nap folyamán: parquet készül, a puffer marad
    assert recorder.compact(cfg, now=day0 + 3_600_000) == 18
    assert buf.exists()
    assert recorder.compact(cfg, now=day0 + 86_400_000) == 18  # lezárt nap: idempotens, puffer törlődik
    assert not buf.exists()
    df = pd.read_parquet(recorder.tick_path(cfg, "ETHUSDT", day0))
    assert len(df) == 3 and {"mark_px", "mid_px", "open_interest", "funding"} <= set(df.columns)


def test_recorder_survives_network_error(cfg):
    logs: list[str] = []
    recorder.run(cfg, hl=FakeHL(fail=True), max_loops=1, log=logs.append)
    assert any("tick hiba" in m for m in logs)


def test_recorder_health_coverage(cfg):
    now = int(pd.Timestamp("2026-10-10 12:00", tz="UTC").timestamp() * 1000)
    start = now - 24 * H
    for i in range(24 * 60):
        if 600 <= i < 630:  # 30 perc kiesés
            continue
        recorder.record_ticks(cfg, FakeHL(), ts_ms=start + i * 60_000)
    recorder.compact(cfg, now=now)
    h = recorder.health(cfg, 24, now=now)["BTCUSDT"]
    assert h["ticks"] == 24 * 60 - 30
    assert h["max_gap_min"] == 30
    assert h["coverage"] == pytest.approx(1 - 30 / 1440)
    assert h["running_hours"] == pytest.approx(24)


def test_missing_bars_grid():
    ts = pd.Series([T0, T0 + H, T0 + 3 * H])
    assert list(store.missing_bars(ts, "1h")) == [pd.Timestamp(T0 + 2 * H, unit="ms", tz="UTC")]


class FakeExchange:
    """A Binance REST: csak a `have` időpontokra ad gyertyát."""

    def __init__(self, have: set[int]):
        self.have = have
        self.calls = 0

    def fapiPublicGetMarkPriceKlines(self, p):
        self.calls += 1
        ts = [t for t in sorted(self.have) if p["startTime"] <= t <= p["endTime"]]
        return [[t, "1", "1", "1", "2", "0", t + H - 1, "0", "0"] for t in ts]


def test_fill_holes_from_api():
    grid = pd.RangeIndex(T0, T0 + 10 * H, H)
    df = pd.DataFrame({"ts": [t for t in grid if t not in (T0 + 3 * H, T0 + 4 * H, T0 + 8 * H)]})
    df = df.assign(open=1.0, high=1.0, low=1.0, close=1.0, volume=0.0, quote_volume=0.0, trades=0)
    ex = FakeExchange({T0 + 3 * H, T0 + 4 * H})  # a 8. óra az API-ban sincs meg: valódi hiány
    out = bb.fill_holes(ex, "markPriceKlines", "BTCUSDT", "1h", df, grid)
    assert ex.calls == 2  # két összefüggő lyuk, két kérés
    assert len(out) == 9 and T0 + 8 * H not in set(out["ts"])
    assert out.loc[out["ts"] == T0 + 3 * H, "close"].item() == 2.0

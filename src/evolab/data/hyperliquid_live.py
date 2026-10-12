"""Hyperliquid nyilvános Info API, kulcs nélkül (spec 2.3). Csak olvasás."""

from __future__ import annotations

import time

import httpx
import pandas as pd

RETRY_SLEEPS = (2, 5, 15)  # 429 / 5xx esetén ennyi mp várakozás próbánként


class HLInfo:
    """`min_interval`: legalább ennyi mp két kérés között (a tömeges pótlás ne fusson bele a 429-be)."""

    def __init__(self, url: str = "https://api.hyperliquid.xyz/info", client: httpx.Client | None = None,
                 min_interval: float = 0.0):
        self.url = url
        self.client = client or httpx.Client(timeout=20)
        self.min_interval = min_interval
        self._last = 0.0

    def _post(self, body: dict):
        for wait in (*RETRY_SLEEPS, None):
            time.sleep(max(0.0, self._last + self.min_interval - time.monotonic()))
            self._last = time.monotonic()
            r = self.client.post(self.url, json=body)
            if (r.status_code == 429 or r.status_code >= 500) and wait is not None:
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r.json()

    def asset_ctxs(self, coins: list[str]) -> pd.DataFrame:
        """Pillanatkép: mark, mid, oracle ár, OI, aktuális funding, impact bid/ask coinonként."""
        meta, ctxs = self._post({"type": "metaAndAssetCtxs"})
        rows = []
        for asset, ctx in zip(meta["universe"], ctxs):
            if asset["name"] in coins:
                rows.append({
                    "coin": asset["name"],
                    "mark_px": float(ctx["markPx"]),
                    "mid_px": float(ctx["midPx"]) if ctx.get("midPx") else float("nan"),
                    "oracle_px": float(ctx["oraclePx"]),
                    "open_interest": float(ctx["openInterest"]),
                    "funding": float(ctx["funding"]),
                    "premium": float(ctx["premium"]) if ctx.get("premium") else float("nan"),
                    "day_ntl_vlm": float(ctx["dayNtlVlm"]),
                    # a tőzsde által számolt „impact” ár egy szabványos névértékű piaci megbízásra:
                    # ebből mérhető a valódi slippage (a mid-től vett távolság)
                    "impact_bid": float(ctx["impactPxs"][0]) if ctx.get("impactPxs") else float("nan"),
                    "impact_ask": float(ctx["impactPxs"][1]) if ctx.get("impactPxs") else float("nan"),
                })
        return pd.DataFrame(rows)

    def candles(self, coin: str, interval: str, start_ms: int, end_ms: int | None = None) -> pd.DataFrame:
        req = {"coin": coin, "interval": interval, "startTime": start_ms}
        if end_ms is not None:
            req["endTime"] = end_ms
        data = self._post({"type": "candleSnapshot", "req": req})
        if not data:
            return pd.DataFrame()
        df = pd.DataFrame(data)
        return pd.DataFrame({
            "ts": df["t"].astype("int64"),
            "open": df["o"].astype(float), "high": df["h"].astype(float),
            "low": df["l"].astype(float), "close": df["c"].astype(float),
            "volume": df["v"].astype(float), "trades": df["n"].astype("int64"),
        })

    def funding_history(self, coin: str, start_ms: int) -> pd.DataFrame:
        data = self._post({"type": "fundingHistory", "coin": coin, "startTime": start_ms})
        if not data:
            return pd.DataFrame()
        df = pd.DataFrame(data)
        return pd.DataFrame({
            "ts": df["time"].astype("int64"),
            "funding_rate": df["fundingRate"].astype(float),
            "premium": df["premium"].astype(float),
        })

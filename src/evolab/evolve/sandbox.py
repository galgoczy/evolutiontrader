"""A fejlesztő-LLM homokozója (docs/02-specifikacio.md 6.3, 9. `test_developer_sandbox`).

Az `evolve/H-*` ágakon csak a `src/evolab/strategy/families/` alatt lehet fájlt létrehozni vagy
módosítani. Ezt három helyen ellenőrizzük: a fejlesztő a commit előtt (`check_changes`), a git
pre-commit hook (`ops/hooks/pre-commit`), és a merge előtt az ág teljes eltérésén (`check_branch`).
Új variáns csak akkor kerül a bíró elé, ha a jövőbe látás próbáján is átmegy (`lookahead_ok`).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pandas as pd

ALLOWED_PREFIX = "src/evolab/strategy/families/"
PROTECTED = ("src/evolab/judge/", "config/judge.yaml", "src/evolab/sim/", "db/schema.sql")
BRANCH_PREFIX = "evolve/H-"


def check_changes(paths: list[str]) -> list[str]:
    """A tiltott útvonalak listája (üres = rendben)."""
    bad = []
    for p in paths:
        p = p.strip()
        if not p:
            continue
        if any(p == x or p.startswith(x) for x in PROTECTED):
            bad.append(f"védett fájl: {p}")
        elif not p.startswith(ALLOWED_PREFIX) or not p.endswith(".py"):
            bad.append(f"a strategy/families/ mappán kívül: {p}")
    return bad


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout


def check_branch(repo: Path, branch: str, base: str = "main") -> list[str]:
    """Az ág teljes eltérése az alaphoz képest: csak strategy/families/ lehet benne."""
    return check_changes(_git(repo, "diff", "--name-only", f"{base}...{branch}").splitlines())


def lookahead_ok(strat, n: int = 900, cut: int = 600, seed: int = 7) -> tuple[bool, str]:
    """Gyors jövőbe-látás próba szintetikus adaton: a `cut` utáni adatok coinonként eltérő, durva
    módosítása nem változtathat korábbi jelet (ugyanaz, mint a `test_no_lookahead`)."""
    rng = np.random.default_rng(seed)
    step = 4 * 3_600_000 if strat.meta.timeframe == "4h" else 3_600_000
    t0 = int(pd.Timestamp("2022-01-01", tz="UTC").timestamp() * 1000)
    ts = t0 + step * np.arange(n)
    frames = []
    for k, sym in enumerate(["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT"]):
        close = 100 * (k + 1) * np.exp(np.cumsum(0.0005 + 0.015 * rng.standard_normal(n)))
        o = np.concatenate([[close[0]], close[:-1]])
        frames.append(pd.DataFrame({"symbol": sym, "ts": ts, "open": o, "high": np.maximum(o, close) * 1.003,
                                    "low": np.minimum(o, close) * 0.997, "close": close, "volume": 1.0,
                                    "mark_close": close,
                                    "funding_rate": np.where(ts % (8 * 3_600_000) == 0, 1e-4 * rng.standard_normal(n), 0.0),
                                    "oi": 1e6 * np.exp(np.cumsum(0.01 * rng.standard_normal(n)))}))
    bars = pd.concat(frames).set_index(["symbol", "ts"]).sort_index()
    labels = np.array(["up/high", "down/low", "flat/mid", "up/mid", "flat/low", "down/high"])
    days = (bars.index.get_level_values("ts") // 86_400_000) % len(labels)
    tv = pd.Series(labels[days], index=bars.index).str.split("/", expand=True)
    regime = pd.DataFrame({"trend": tv[0], "vol": tv[1], "positioning": "neutral"}, index=bars.index)
    shocked = bars.copy()
    fut = shocked.index.get_level_values("ts") >= t0 + step * cut
    for k, sym in enumerate(["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT"]):
        rows = fut & (shocked.index.get_level_values("symbol") == sym)
        shocked.loc[rows, ["open", "high", "low", "close", "mark_close"]] *= (0.5 + 0.4 * k)
    shocked.loc[fut, "oi"] *= 7
    try:
        a = strat.signals(bars, regime)
        b = strat.signals(shocked, regime)
    except Exception as e:
        return False, f"a jel hibát dobott: {type(e).__name__}: {e}"
    past = a.index.get_level_values("ts") < t0 + step * cut
    try:
        pd.testing.assert_frame_equal(a[past], b[past])
    except AssertionError as e:
        return False, f"jövőbe látás: egy jövőbeli módosítás megváltoztatta a korábbi jelet ({str(e)[:120]})"
    if (a["target_position"] == 0).all():
        return False, "a variáns szintetikus adaton egyetlen pozíciót sem nyit"
    return True, "ok"

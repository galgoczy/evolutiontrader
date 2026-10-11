"""Méretezés és megszakítók (spec 4., `config/lab.yaml` `risk`), minden stratégiára egyformán.

Méretezés (volatilitás-cél, egyenlő kockázati súly coinonként): belépéskor a coin-pozíció
névértéke a tőke arányában
    |súly| = |target| * min((vol_target_daily / N) / napi_vol, max_weight_per_coin),
ahol N az univerzum coinjainak száma, a napi vol a jel-gyertyáig számolt 30 napos realizált vol.
Így a napi 1% a PORTFÓLIÓ kockázati költségvetése: ha minden coin teljesen együtt mozog és
minden pozíció egy irányba áll, a portfólió napi vol-ja ~1%. A portfólió
bruttó kitettsége legfeljebb `max_gross_leverage` x tőke: ami nem fér bele, azt a belépés levágja.
A méret a kötés teljes idejére rögzített (nincs vol-újrasúlyozás tartás közben).

Megszakítók (a stratégia egész portfóliójára):
- `consecutive_losses` egymást követő vesztes kötés -> 24 óra szünet,
- napi DD: az utolsó 24 óra equity-csúcsától `daily_dd_pct` esés -> 24 óra szünet,
- heti DD: az utolsó 7 nap equity-csúcsától `weekly_dd_pct` esés -> a futás `failed`, minden
  pozíció zár, a futás leáll (ez bukás a bírónál).
Szünet alatt új pozíció nem nyílik, a meglévők a saját jelük/stopjuk szerint zárhatnak.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np
import pandas as pd

from evolab.data.universe import tf_ms

DAY_MS = 86_400_000
VOL_DAYS = 30


@dataclass(frozen=True)
class RiskParams:
    vol_target_daily: float
    max_gross_leverage: float
    max_weight_per_coin: float
    consecutive_losses: int
    daily_dd_pct: float
    weekly_dd_pct: float
    pause_ms: int = DAY_MS

    @classmethod
    def from_config(cls, risk: dict) -> "RiskParams":
        b = risk["breakers"]
        return cls(float(risk["vol_target_daily"]), float(risk["max_gross_leverage"]),
                   float(risk["max_weight_per_coin"]), int(b["consecutive_losses"]),
                   float(b["daily_dd_pct"]), float(b["weekly_dd_pct"]))


def daily_vol(close: pd.Series, tf: str, days: int = VOL_DAYS) -> pd.Series:
    """Napi realizált vol a gyertya-idősík log-hozamaiból, `days` napos ablakon (kauzális)."""
    per_day = DAY_MS // tf_ms(tf)
    r = np.log(close).diff()
    return r.rolling(days * per_day, min_periods=days * per_day).std() * np.sqrt(per_day)


def vol_target_weight(target: float, vol: float, p: RiskParams, n_coins: int) -> float:
    """Előjeles célsúly (névérték / tőke). Bemelegedés alatt (nincs vol) 0."""
    if target == 0 or not vol > 0:
        return 0.0
    budget = p.vol_target_daily / n_coins
    return float(np.sign(target)) * abs(target) * min(budget / vol, p.max_weight_per_coin)


class Breakers:
    """A megszakítók állapota egy futáson belül."""

    def __init__(self, p: RiskParams):
        self.p = p
        self.losses = 0
        self.pause_until = -1
        self.failed_at: int | None = None
        self.events: list[dict] = []
        self._hist: deque[tuple[int, float]] = deque()  # (ts, equity) az utolsó 7 napra

    def paused(self, ts: int) -> bool:
        return ts < self.pause_until

    def _pause(self, ts: int, reason: str) -> None:
        if not self.paused(ts):
            self.pause_until = ts + self.p.pause_ms
            self.events.append({"ts": ts, "event": "pause", "reason": reason})

    def on_trade_closed(self, ts: int, pnl: float) -> None:
        self.losses = self.losses + 1 if pnl < 0 else 0
        if self.losses >= self.p.consecutive_losses:
            self.losses = 0
            self._pause(ts, f"{self.p.consecutive_losses} egymást követő vesztes kötés")

    def on_equity(self, ts: int, equity: float) -> None:
        """Gyertyazáráskor hívandó (`ts` = a zárás ideje)."""
        self._hist.append((ts, equity))
        while self._hist and self._hist[0][0] <= ts - 7 * DAY_MS:
            self._hist.popleft()
        week_peak = max(e for _, e in self._hist)
        day_peak = max(e for t, e in self._hist if t > ts - DAY_MS)
        if self.failed_at is None and equity <= week_peak * (1 - self.p.weekly_dd_pct / 100):
            self.failed_at = ts
            self.events.append({"ts": ts, "event": "failed", "reason": f"heti DD >= {self.p.weekly_dd_pct}%"})
        elif equity <= day_peak * (1 - self.p.daily_dd_pct / 100):
            self._pause(ts, f"napi DD >= {self.p.daily_dd_pct}%")

"""Portfólió-szimulátor (spec 4.): gyertyánként lépő elszámolás, vektorizált előkészítéssel.

Egy gyertya (i) menete:
1. NYITÓ: a jel-gyertya (i-1) `target_position`-je szerint előbb a zárások, aztán a nyitások,
   a nyitó áron, taker díjjal és slippage-dzsel. A célérték változása (pl. +1 -> -1, +1 -> 0,5)
   zárás + új nyitás.
2. GYERTYÁN BELÜL: stop és take-profit a high/low érintésekor; ha a nyitó már a szinten túl van,
   a nyitón teljesül. Ha egy gyertyában a stop és a TP is érintett, a stop számít. Stop/TP után a
   coin addig lapos, amíg a jel célértéke meg nem változik (különben azonnal visszalépne).
3. ZÁRÁS: funding az akkor tartott pozícióra (mark áron), equity mark áron, megszakítók.

PnL és equity mark áron, teljesülés last (gyertya) áron. Determinisztikus: nincs véletlen.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd

from evolab.data.universe import tf_ms
from evolab.features.indicators import atr as atr_ind
from evolab.sim import funding as funding_mod
from evolab.sim.costs import Costs
from evolab.sim.risk import Breakers, RiskParams, daily_vol, vol_target_weight

INITIAL_CAPITAL = 10_000.0
TRADE_COLUMNS = ["symbol", "side", "qty", "entry_ts", "entry_price", "exit_ts", "exit_price", "fees",
                 "funding", "slippage", "pnl", "entry_reason", "exit_reason", "regime", "mode"]

# (symbol, target, napi vol, tőke) -> előjeles súly. Alapból vol-cél; teszt felülírhatja.
Sizer = Callable[[str, float, float, float], float]


@dataclass
class Result:
    trades: pd.DataFrame
    equity: pd.DataFrame
    exposure: pd.DataFrame
    events: pd.DataFrame
    status: str
    initial_capital: float
    skipped_entries: int = 0
    meta: dict = field(default_factory=dict)
    open_positions: pd.DataFrame = field(default_factory=pd.DataFrame)

    def trades_hash(self) -> str:
        """A kötéslista ujjlenyomata (determinizmus-teszt, spec 4.)."""
        csv = self.trades.to_csv(index=False, float_format="%.10g")
        return hashlib.sha256(csv.encode()).hexdigest()

    def summary(self) -> dict:
        """Egyszerű összefoglaló a parancssorhoz. A bíró mutatói a 3. fázisban jönnek (judge/)."""
        eq = self.equity["equity"]
        pnl = self.trades["pnl"] if not self.trades.empty else pd.Series(dtype=float)
        gross_loss = -pnl[pnl < 0].sum()
        return {
            "status": self.status,
            "trades": int(len(self.trades)),
            "final_equity": round(float(eq.iloc[-1]), 2) if len(eq) else self.initial_capital,
            "total_return_pct": round(100 * (float(eq.iloc[-1]) / self.initial_capital - 1), 2) if len(eq) else 0.0,
            "max_dd_pct": round(100 * float((1 - eq / eq.cummax()).max()), 2) if len(eq) else 0.0,
            "profit_factor": round(float(pnl[pnl > 0].sum() / gross_loss), 3) if gross_loss > 0 else None,
            "fees": round(float(self.trades["fees"].sum()), 2) if len(pnl) else 0.0,
            "funding": round(float(self.trades["funding"].sum()), 2) if len(pnl) else 0.0,
            "skipped_entries": self.skipped_entries,
        }


@dataclass
class _Pos:
    qty: float
    target: float
    entry_ts: int
    entry_price: float
    fees: float
    slippage: float
    reason: str
    regime: str
    funding: float = 0.0


def _wide(s: pd.Series, ts: np.ndarray, syms: list[str]) -> np.ndarray:
    return s.unstack("symbol").reindex(index=ts, columns=syms).to_numpy()


def run(bars: pd.DataFrame, signals: pd.DataFrame, tf: str, costs: Costs, risk: RiskParams,
        regime: pd.DataFrame | None = None, initial_capital: float = INITIAL_CAPITAL,
        sizer: Sizer | None = None, mode: str = "backtest", close_at_end: bool = True) -> Result:
    """`close_at_end=False` (paper): a végén nyitva maradt pozíció nyitva marad, a mark áron
    értékelve, és a `Result.open_positions` sorolja fel; a kötéslista csak a lezártakat tartalmazza."""
    step = tf_ms(tf)
    if bars.empty:  # pl. a paper első órái: még nincs lezárt gyertya a kezdet után
        return Result(pd.DataFrame(columns=TRADE_COLUMNS), pd.DataFrame(columns=["ts", "equity", "gross_exposure"]),
                      pd.DataFrame(columns=["ts"]), pd.DataFrame(columns=["ts", "event", "reason"]), "ok",
                      initial_capital)
    syms = list(dict.fromkeys(bars.index.get_level_values("symbol")))
    ts = np.array(sorted(set(bars.index.get_level_values("ts"))), dtype="int64")
    n_t, n_s = len(ts), len(syms)

    # --- vektorizált előkészítés (coinonként kauzális indikátorok)
    groups = [d for _, d in bars.groupby(level="symbol", sort=False)]
    atr_s = pd.concat([atr_ind(d, 14) for d in groups])
    vol_s = pd.concat([daily_vol(d["close"], tf) for d in groups])
    O, H, L, C = (_wide(bars[c], ts, syms) for c in ("open", "high", "low", "close"))
    M = _wide(bars["mark_close"].fillna(bars["close"]), ts, syms)
    F = _wide(bars["funding_rate"].fillna(0.0) if "funding_rate" in bars else bars["close"] * 0, ts, syms)
    ATR, VOL = _wide(atr_s, ts, syms), _wide(vol_s, ts, syms)
    TGT = np.nan_to_num(_wide(signals["target_position"], ts, syms))
    STOP, TP = _wide(signals["stop_price"], ts, syms), _wide(signals["take_profit_price"], ts, syms)
    REASON = signals["reason"].unstack("symbol").reindex(index=ts, columns=syms).fillna("").to_numpy()
    valid = ~np.isnan(O)
    if regime is not None and not regime.empty:
        lab = (regime["trend"].astype(str) + "/" + regime["vol"].astype(str)).where(regime["trend"].notna(), "")
        REG = lab.unstack("symbol").reindex(index=ts, columns=syms).fillna("").to_numpy()
    else:
        REG = np.full((n_t, n_s), "", dtype=object)

    size = sizer or (lambda sym, target, vol, equity: vol_target_weight(target, vol, risk, n_s))
    br = Breakers(risk)
    cash = initial_capital
    pos: list[_Pos | None] = [None] * n_s
    blocked: list[float | None] = [None] * n_s
    last_mark = np.full(n_s, np.nan)
    equity_prev = initial_capital
    trades: list[dict] = []
    eq_rows: list[tuple] = []
    expo_rows: list[np.ndarray] = []
    skipped = 0
    status = "ok"

    def close(j: int, t: int, raw: float, reason: str) -> None:
        nonlocal cash
        p = pos[j]
        side = 1 if p.qty > 0 else -1
        fill = costs.fill_price(raw, -side, ATR[i - 1, j] if i > 0 else np.nan)
        fee = costs.fee(p.qty * fill)
        cash += p.qty * fill - fee
        pnl = p.qty * (fill - p.entry_price) - p.fees - fee + p.funding
        trades.append({
            "symbol": syms[j], "side": side, "qty": abs(p.qty), "entry_ts": p.entry_ts,
            "entry_price": p.entry_price, "exit_ts": t, "exit_price": fill, "fees": p.fees + fee,
            "funding": p.funding, "slippage": p.slippage + abs(p.qty) * abs(fill - raw), "pnl": pnl,
            "entry_reason": p.reason, "exit_reason": reason, "regime": p.regime, "mode": mode,
        })
        pos[j] = None
        br.on_trade_closed(t, pnl)

    for i in range(n_t):
        t = int(ts[i])
        # --- 1. nyitó: zárások, majd nyitások a jel-gyertya célértéke szerint
        failed = br.failed_at is not None
        desired = [TGT[i - 1, j] if i > 0 and valid[i - 1, j] else 0.0 for j in range(n_s)]
        for j in range(n_s):
            if valid[i, j] and pos[j] is not None and (failed or desired[j] != pos[j].target):
                close(j, t, O[i, j], "breaker_failed" if failed else "signal")
        if failed:
            status = "failed"
            eq = cash + sum(p.qty * last_mark[j] for j, p in enumerate(pos) if p is not None)
            eq_rows.append((t, eq, 0.0))
            expo_rows.append(np.zeros(n_s))
            break
        for j in range(n_s):
            d = desired[j]
            if blocked[j] is not None and d != blocked[j]:
                blocked[j] = None
            if not valid[i, j] or pos[j] is not None or d == 0 or blocked[j] is not None or br.paused(t):
                continue
            w = size(syms[j], d, VOL[i - 1, j], equity_prev)
            gross = sum(abs(p.qty) * O[i, k] for k, p in enumerate(pos) if p is not None and valid[i, k])
            notional = min(abs(w) * equity_prev, risk.max_gross_leverage * equity_prev - gross)
            if w == 0 or notional <= 0:
                skipped += w != 0
                continue
            side = 1 if w > 0 else -1
            fill = costs.fill_price(O[i, j], side, ATR[i - 1, j])
            qty = side * notional / fill
            fee = costs.fee(qty * fill)
            cash -= qty * fill + fee
            pos[j] = _Pos(qty, d, t, fill, fee, abs(qty) * abs(fill - O[i, j]), REASON[i - 1, j], REG[i, j])

        # --- 2. gyertyán belül: stop / take-profit (a stop elsőbbséget élvez)
        for j in range(n_s):
            p = pos[j]
            if p is None or not valid[i, j] or i == 0:
                continue
            stop, tp = STOP[i - 1, j], TP[i - 1, j]
            long = p.qty > 0
            hit_stop = stop == stop and (L[i, j] <= stop if long else H[i, j] >= stop)
            hit_tp = tp == tp and (H[i, j] >= tp if long else L[i, j] <= tp)
            if hit_stop:
                raw = min(O[i, j], stop) if long else max(O[i, j], stop)
                close(j, t, raw, "stop")
                blocked[j] = desired[j]
            elif hit_tp:
                raw = max(O[i, j], tp) if long else min(O[i, j], tp)
                close(j, t, raw, "take_profit")
                blocked[j] = desired[j]

        # --- 3. zárás: funding, mark-equity, megszakítók
        for j in range(n_s):
            if not valid[i, j]:
                continue
            last_mark[j] = M[i, j]
            p = pos[j]
            if p is not None and F[i, j] != 0:
                pay = funding_mod.payment(p.qty, M[i, j], F[i, j])
                cash += pay
                p.funding += pay
        notional = np.array([p.qty * last_mark[j] if p is not None else 0.0 for j, p in enumerate(pos)])
        equity = cash + notional.sum()
        eq_rows.append((t + step, equity, np.abs(notional).sum() / equity if equity > 0 else np.nan))
        expo_rows.append(notional / equity if equity > 0 else notional * np.nan)
        br.on_equity(t + step, equity)
        equity_prev = equity

    open_rows = [{"symbol": syms[j], "side": 1 if p.qty > 0 else -1, "qty": abs(p.qty), "entry_ts": p.entry_ts,
                  "entry_price": p.entry_price, "mark": float(last_mark[j]), "fees": p.fees, "funding": p.funding,
                  "unrealized": p.qty * (last_mark[j] - p.entry_price), "entry_reason": p.reason,
                  "regime": p.regime} for j, p in enumerate(pos) if p is not None]
    # --- a futás végén nyitva maradt pozíciók zárása az utolsó záróáron
    if status == "ok" and close_at_end:
        open_rows = []
        failed_last = br.failed_at is not None  # a heti DD épp az utolsó gyertyán oldott ki
        status = "failed" if failed_last else "ok"
        i = n_t - 1
        for j in range(n_s):
            if pos[j] is not None:
                close(j, int(ts[i]) + step, C[i, j] if valid[i, j] else last_mark[j],
                      "breaker_failed" if failed_last else "end")
        if eq_rows:
            eq_rows[-1] = (eq_rows[-1][0], cash, 0.0)
    if br.failed_at is not None:
        status = "failed"

    equity_df = pd.DataFrame(eq_rows, columns=["ts", "equity", "gross_exposure"])
    exposure_df = pd.DataFrame(np.array(expo_rows).reshape(-1, n_s), columns=syms)
    exposure_df.insert(0, "ts", equity_df["ts"].to_numpy())
    return Result(
        trades=pd.DataFrame(trades, columns=TRADE_COLUMNS),
        equity=equity_df, exposure=exposure_df,
        events=pd.DataFrame(br.events, columns=["ts", "event", "reason"]),
        status=status, initial_capital=initial_capital, skipped_entries=int(skipped),
        open_positions=pd.DataFrame(open_rows),
    )

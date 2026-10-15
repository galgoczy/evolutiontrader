"""HMM-alapú rezsimcímke mint VARIÁNS (docs/02-specifikacio.md 2.4, 7. fázis).

4 állapotú Gauss-HMM coinonként, napi bemenettel: [log-hozam, a 10 napos realizált vol logaritmusa].
Walk-forward: `refit_days` naponta újraillesztés KIZÁRÓLAG az addigi adaton; a következő
`refit_days` nap címkéje az előre-szűrt (forward) állapot-valószínűségből jön, ami a t. napig látó
adatot használja (nem a teljes sor Viterbi- vagy simított becslését, az a jövőbe látna).
Állapot -> címke az illesztéskori állapotátlagok rangja szerint: hozam szerint a legalacsonyabb
`down`, a legmagasabb `up`, a középső kettő `flat`; vol szerint a legalacsonyabb `low`, a legmagasabb
`high`, a többi `mid`. A pozícionáltság a szabályalapú címkéből jön (a HMM azt nem modellezi).
Kimenet: `regime_daily_hmm` tábla, ugyanazzal a `date` szemantikával, mint a `regime_daily`.
"""

from __future__ import annotations

import logging
import warnings

import numpy as np
import pandas as pd
from scipy.special import logsumexp
from scipy.stats import multivariate_normal

from evolab.config import Config
from evolab.data import store
from evolab.data.universe import symbols
from evolab.db import connect, init_db

logging.getLogger("hmmlearn").setLevel(logging.ERROR)  # „Model is not converging” zaj a naplóban

DEFAULTS = {"n_states": 4, "refit_days": 30, "min_history": 365, "vol_window": 10, "seed": 7}


def features(daily: pd.DataFrame, vol_window: int) -> pd.DataFrame:
    d = daily.sort_values("ts").reset_index(drop=True)
    r = np.log(d["close"]).diff()
    v = np.log(r.rolling(vol_window).std() + 1e-8)
    return pd.DataFrame({"ts": d["ts"], "ret": r, "logvol": v}).dropna().reset_index(drop=True)


def _fit(x: np.ndarray, n: int, seed: int):
    from hmmlearn.hmm import GaussianHMM

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        m = GaussianHMM(n_components=n, covariance_type="full", n_iter=200, random_state=seed)
        m.fit(x)
    return m


def forward_filter(model, x: np.ndarray) -> np.ndarray:
    """Előre-szűrt állapot-valószínűségek: az i. sor csak az x[:i+1] adatból (log-térben)."""
    k = model.n_components
    logb = np.column_stack([multivariate_normal(model.means_[j], model.covars_[j], allow_singular=True).logpdf(x)
                            for j in range(k)])
    loga = np.log(model.transmat_ + 1e-300)
    alpha = np.empty_like(logb)
    alpha[0] = np.log(model.startprob_ + 1e-300) + logb[0]
    alpha[0] -= logsumexp(alpha[0])
    for t in range(1, len(x)):
        alpha[t] = logsumexp(alpha[t - 1][:, None] + loga, axis=0) + logb[t]
        alpha[t] -= logsumexp(alpha[t])
    return np.exp(alpha)


def state_labels(model) -> tuple[dict[int, str], dict[int, str]]:
    ret_rank = np.argsort(np.argsort(model.means_[:, 0]))
    vol_rank = np.argsort(np.argsort(model.means_[:, 1]))
    k = model.n_components
    trend = {j: "down" if ret_rank[j] == 0 else "up" if ret_rank[j] == k - 1 else "flat" for j in range(k)}
    vol = {j: "low" if vol_rank[j] == 0 else "high" if vol_rank[j] == k - 1 else "mid" for j in range(k)}
    return trend, vol


def label(daily: pd.DataFrame, p: dict | None = None) -> pd.DataFrame:
    """HMM-címkék egy coinra (date, trend, vol). Az első `min_history` nap kimarad."""
    p = {**DEFAULTS, **(p or {})}
    f = features(daily, p["vol_window"])
    x = f[["ret", "logvol"]].to_numpy()
    rows = []
    for start in range(p["min_history"], len(f), p["refit_days"]):
        model = _fit(x[:start], p["n_states"], p["seed"])          # csak a `start` előtti adat
        end = min(start + p["refit_days"], len(f))
        probs = forward_filter(model, x[:end])                     # szűrés az addigi adaton
        trend, vol = state_labels(model)
        for i in range(start, end):
            s = int(np.argmax(probs[i]))
            rows.append((f["ts"].iloc[i], trend[s], vol[s]))
    out = pd.DataFrame(rows, columns=["ts", "trend", "vol"])
    out["date"] = pd.to_datetime(out["ts"], unit="ms", utc=True).dt.strftime("%Y-%m-%d")
    return out[["date", "trend", "vol"]]


def update(cfg: Config, symbol_list: list[str] | None = None) -> int:
    """A `regime_daily_hmm` tábla újraszámolása (a pozícionáltság a szabályalapú táblából)."""
    init_db(cfg)
    n = 0
    with connect(cfg.db_path) as conn:
        pos = pd.read_sql_query("SELECT date, symbol, positioning FROM regime_daily", conn)
        for sym in symbol_list or symbols(cfg):
            daily = store.read_bars(cfg, sym, "1d")
            if len(daily) < DEFAULTS["min_history"] + 30:
                continue
            lab = label(daily).assign(symbol=sym)
            lab = lab.merge(pos, on=["date", "symbol"], how="left").fillna({"positioning": "neutral"})
            conn.executemany("INSERT OR REPLACE INTO regime_daily_hmm(date, symbol, trend, vol, positioning) "
                             "VALUES (?, ?, ?, ?, ?)",
                             lab[["date", "symbol", "trend", "vol", "positioning"]].itertuples(index=False, name=None))
            n += len(lab)
    return n


def compare(cfg: Config, min_trades: int | None = None) -> pd.DataFrame:
    """Melyik címke mellett jobb a populáció (spec 2.4): a legutolsó L1-ítéletek kötéseit mindkét
    címkézővel újracímkézve, a rezsim-kapu szerinti pozitív kombinációk száma és az EV-szórás
    (mennyire különíti el a címkéző a jó és rossz időszakokat)."""
    from pathlib import Path

    from evolab.evolve.population import latest_verdicts
    from evolab.judge.gates import positive_regimes

    min_trades = min_trades or cfg.judge["L1_backtest"]["regime_min_trades"]
    with connect(cfg.db_path) as conn:
        hmm = pd.read_sql_query("SELECT date, symbol, trend, vol FROM regime_daily_hmm", conn)
    lab = {(r.symbol, r.date): f"{r.trend}/{r.vol}" for r in hmm.itertuples()}
    rows = []
    for r in latest_verdicts(cfg).itertuples():
        out = Path(json_get(r.is_metrics_json, "out_dir") or "")
        if not (out / "trades.parquet").exists():
            continue
        t = pd.read_parquet(out / "trades.parquet")
        prev = pd.to_datetime(t["entry_ts"] // 86_400_000 * 86_400_000 - 86_400_000, unit="ms", utc=True)
        t["regime_hmm"] = [lab.get((s, d), "") for s, d in zip(t["symbol"], prev.dt.strftime("%Y-%m-%d"))]
        ev = {}
        for col in ("regime", "regime_hmm"):
            g = t[t[col] != ""].groupby(col)["pnl"].agg(["count", "mean"])
            ev[col] = {k: {"trades": int(v["count"]), "ev": float(v["mean"])} for k, v in g.iterrows()}
        rows.append({"strategy_id": r.strategy_id, "family": r.family,
                     "pos_rule": positive_regimes(ev["regime"], min_trades),
                     "pos_hmm": positive_regimes(ev["regime_hmm"], min_trades),
                     "ev_spread_rule": _spread(ev["regime"], min_trades), "ev_spread_hmm": _spread(ev["regime_hmm"], min_trades)})
    return pd.DataFrame(rows)


def json_get(text: str | None, key: str):
    import json

    try:
        return json.loads(text or "{}").get(key)
    except ValueError:
        return None


def _spread(ev: dict, min_trades: int) -> float:
    vals = [v["ev"] for v in ev.values() if v["trades"] >= min_trades]
    return float(np.std(vals)) if len(vals) > 1 else 0.0

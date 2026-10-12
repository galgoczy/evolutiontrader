"""7. fázis: diverzitás-büntetés, HMM rezsimcímke-variáns, őr (hibakezelés)."""

import datetime as dt
import json

import numpy as np
import pandas as pd
import pytest

from evolab.data import store
from evolab.db import connect, init_db
from evolab.features import regime_hmm
from evolab.judge.diversity import penalized_ranking
from evolab.notify import watchdog

DAY = 86_400_000
T0 = int(pd.Timestamp("2021-01-01", tz="UTC").timestamp() * 1000)


# ---------------------------------------------------------------- diverzitás


def test_diversity_penalizes_weaker_of_correlated_pair():
    rng = np.random.default_rng(0)
    base = rng.standard_normal(300)
    rets = pd.DataFrame({"a": base, "b": base + 0.1 * rng.standard_normal(300),   # a ~ b
                         "c": rng.standard_normal(300),
                         "d": base + 0.1 * rng.standard_normal(300)})           # d ~ a ~ b
    dsr = pd.Series({"a": 0.9, "b": 0.8, "c": 0.7, "d": 0.6})
    r = penalized_ranking(dsr, rets, corr_max=0.8, penalty=0.9).set_index("strategy_id")
    assert r.loc["a", "dsr_ranked"] == 0.9 and r.loc["c", "dsr_ranked"] == 0.7      # a legerősebb és a független
    assert r.loc["b", "dsr_ranked"] == pytest.approx(0.72)                          # egyszer büntetve
    assert r.loc["d", "dsr_ranked"] == pytest.approx(0.54) and "a" in r.loc["d", "penalized_by"]
    assert list(r.index) == ["a", "b", "c", "d"]  # 0.9, 0.72, 0.7, 0.54


# ---------------------------------------------------------------- HMM


def _daily(n=700, seed=1):
    rng = np.random.default_rng(seed)
    vol = np.repeat([0.01, 0.04, 0.02, 0.05], n // 4 + 1)[:n]
    drift = np.repeat([0.002, -0.003, 0.0, 0.003], n // 4 + 1)[:n]
    close = 100 * np.exp(np.cumsum(drift + vol * rng.standard_normal(n)))
    return pd.DataFrame({"ts": T0 + DAY * np.arange(n), "close": close})


P = {"min_history": 200, "refit_days": 60}


def test_hmm_forward_filter_is_causal():
    f = regime_hmm.features(_daily(), 10)
    x = f[["ret", "logvol"]].to_numpy()
    m = regime_hmm._fit(x[:300], 4, 7)
    full, part = regime_hmm.forward_filter(m, x), regime_hmm.forward_filter(m, x[:400])
    np.testing.assert_allclose(full[:400], part)  # az első 400 sor nem függ a későbbi adattól


def test_hmm_labels_ignore_future():
    d = _daily()
    base = regime_hmm.label(d, P)
    shocked = d.copy()
    shocked.loc[shocked.index >= 500, "close"] *= np.linspace(1, 4, len(shocked) - 500)
    lab = regime_hmm.label(shocked, P)
    cut = pd.Timestamp(T0 + 500 * DAY, unit="ms", tz="UTC").strftime("%Y-%m-%d")
    pd.testing.assert_frame_equal(base[base["date"] < cut].reset_index(drop=True),
                                  lab[lab["date"] < cut].reset_index(drop=True))
    assert set(base["trend"]) <= {"up", "down", "flat"} and set(base["vol"]) <= {"low", "mid", "high"}
    assert base["date"].iloc[0] > pd.Timestamp(T0, unit="ms").strftime("%Y-%m-%d")  # bemelegedés kimarad


def test_hmm_update_writes_table(cfg):
    init_db(cfg)
    d = _daily(n=500).assign(open=0.0, high=0.0, low=0.0, volume=0.0, quote_volume=0.0, trades=0,
                             mark_close=0.0, premium_close=0.0)
    store.write_parquet(d[store.BAR_COLUMNS], store.bars_path(cfg, "BTCUSDT", "1d"))
    n = regime_hmm.update(cfg, ["BTCUSDT"])
    with connect(cfg.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM regime_daily_hmm").fetchone()[0] == n > 0


# ---------------------------------------------------------------- őr


def _runs(cfg, paper_at, daily_at, paper_status="ok"):
    init_db(cfg)
    with connect(cfg.db_path) as conn:
        conn.execute("INSERT INTO runs(kind, step, status, message, started_at, finished_at) "
                     "VALUES ('paper', 'run', ?, 'x', ?, ?)", (paper_status, paper_at, paper_at))
        conn.execute("INSERT INTO runs(kind, step, status, started_at) VALUES ('daily', "
                     "'data,judge,report,researcher,developer,ladder', 'ok', ?)", (daily_at,))


def _tick(cfg, ts_ms):
    p = store.data_dir(cfg) / "hl" / "buffer" / "ticks_x.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"ts": ts_ms, "symbol": "BTCUSDT"}) + "\n")


def test_watchdog_detects_and_recovers(cfg):
    now = dt.datetime(2026, 10, 13, 12, 0, tzinfo=dt.UTC)
    iso = lambda h: (now - dt.timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    _tick(cfg, int((now - dt.timedelta(minutes=30)).timestamp() * 1000))
    _runs(cfg, iso(5), iso(30))
    probs = watchdog.problems(cfg, now, disk_free_gb=2.0)
    assert set(probs) == {"recorder", "paper", "daily", "disk"}

    sent = []
    watchdog.run(cfg, send=sent.append, now=now, disk_free_gb=2.0)
    assert len(sent) == 4
    watchdog.run(cfg, send=sent.append, now=now + dt.timedelta(hours=1), disk_free_gb=2.0)
    assert len(sent) == 4                                   # 6 órán belül nem ismétel
    _tick(cfg, int(now.timestamp() * 1000))
    watchdog.run(cfg, send=sent.append, now=now + dt.timedelta(minutes=5), disk_free_gb=2.0)
    assert sent[-1] == "✅ EvolutionTrader: rendben (recorder)"
    watchdog.run(cfg, send=sent.append, now=now + dt.timedelta(hours=7), disk_free_gb=2.0)
    assert any("kevés a szabad hely" in s for s in sent[-4:])  # 6 óra után újra szól


def test_watchdog_quiet_when_healthy_and_respects_stop(cfg):
    now = dt.datetime(2026, 10, 13, 12, 0, tzinfo=dt.UTC)
    iso = lambda h: (now - dt.timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    _tick(cfg, int((now - dt.timedelta(minutes=2)).timestamp() * 1000))
    _runs(cfg, iso(0.5), iso(10))
    assert watchdog.problems(cfg, now, disk_free_gb=100.0) == {}
    _runs(cfg, iso(9), iso(10))
    cfg.stop_file.write_text("")
    assert watchdog.problems(cfg, now, disk_free_gb=100.0) == {}   # STOP: a paper szándékosan áll

"""0. fázis: váz, konfiguráció, adatbázis, CLI."""

import sqlite3

import pytest

from evolab import __version__
from evolab import cli
from evolab.cli import main
from evolab.db import connect, init_db, list_tables


def test_version(capsys):
    with pytest.raises(SystemExit) as e:
        main(["--version"])
    assert e.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_config_loads(cfg):
    assert cfg.lab["universe"] == ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT"]
    assert cfg.lab["holdout_months"] == 6
    assert cfg.judge_version >= 1
    assert cfg.judge["changelog"], "a judge.yaml-ban kötelező a changelog"
    total = sum(f["initial_variants"] for f in cfg.families["families"].values())
    assert total == cfg.lab["population"]["initial"] == 40


def test_init_db_idempotent(cfg):
    init_db(cfg)
    init_db(cfg)
    with connect(cfg.db_path) as conn:
        tables = set(list_tables(conn))
    assert {"trials", "strategies", "hypotheses", "ladder_events", "runs", "regime_daily"} <= tables


def _insert_trial(conn, trial_id="t1"):
    conn.execute(
        "INSERT INTO trials(trial_id, strategy_id, family, params_hash, data_hash, judge_version) "
        "VALUES (?, 's1', 'trend', 'p', 'd', 1)",
        (trial_id,),
    )


def test_ledger_append_only(cfg):
    init_db(cfg)
    with connect(cfg.db_path) as conn:
        _insert_trial(conn)
    with connect(cfg.db_path) as conn:
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            conn.execute("UPDATE trials SET dsr = 0.99 WHERE trial_id = 't1'")
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            conn.execute("DELETE FROM trials WHERE trial_id = 't1'")
        assert conn.execute("SELECT COUNT(*) FROM trials").fetchone()[0] == 1


def test_daily_without_telegram(cfg, capsys, monkeypatch):
    # az 1. fázistól a `data` lépés valódi letöltés; itt csonkkal helyettesítjük (nincs hálózat)
    monkeypatch.setitem(cli.STEP_FUNCS, "data", lambda cfg: "csonk")
    assert main(["daily"]) == 0
    out = capsys.readouterr().out
    assert "Telegram kihagyva" in out
    with connect(cfg.db_path) as conn:
        row = conn.execute("SELECT status FROM runs ORDER BY run_id DESC LIMIT 1").fetchone()
    assert row["status"] == "ok"


def test_daily_step_error_reported(cfg, capsys, monkeypatch):
    def boom(cfg):
        raise RuntimeError("letöltési hiba")

    monkeypatch.setitem(cli.STEP_FUNCS, "data", boom)
    assert main(["daily"]) == 1
    assert "HIBA: letöltési hiba" in capsys.readouterr().out
    with connect(cfg.db_path) as conn:
        row = conn.execute("SELECT status FROM runs ORDER BY run_id DESC LIMIT 1").fetchone()
    assert row["status"] == "error"


def test_status(cfg, capsys):
    init_db(cfg)
    assert main(["status"]) == 0
    assert "Bíró verzió" in capsys.readouterr().out

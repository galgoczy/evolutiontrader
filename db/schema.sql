-- EvolutionTrader állapot-adatbázis (SQLite, data/lab.db)
-- Idempotens: többször futtatható.
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Stratégia-egyedek és szintjük a létrán
CREATE TABLE IF NOT EXISTS strategies (
    strategy_id   TEXT PRIMARY KEY,
    family        TEXT NOT NULL,
    parent_id     TEXT,
    hypothesis_id TEXT,
    timeframe     TEXT NOT NULL,
    params_json   TEXT NOT NULL DEFAULT '{}',
    file_path     TEXT NOT NULL,
    level         TEXT NOT NULL DEFAULT 'L0' CHECK (level IN ('L0','L1','L2','L3','L4','retired')),
    status        TEXT NOT NULL DEFAULT 'active',
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

-- Kutatói hipotézisek
CREATE TABLE IF NOT EXISTS hypotheses (
    hypothesis_id      TEXT PRIMARY KEY,
    family             TEXT NOT NULL,
    parent_strategy_id TEXT,
    mutation_type      TEXT NOT NULL,
    change             TEXT NOT NULL,
    rationale          TEXT NOT NULL,
    expected_regimes   TEXT,
    falsifier          TEXT NOT NULL,
    param_grid_json    TEXT,
    status             TEXT NOT NULL DEFAULT 'new',
    created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

-- Kísérletnapló: CSAK BESZÚRHATÓ (a deflated Sharpe bemenete, a bukottak is)
CREATE TABLE IF NOT EXISTS trials (
    trial_id              TEXT PRIMARY KEY,
    strategy_id           TEXT NOT NULL,
    family                TEXT NOT NULL,
    hypothesis_id         TEXT,
    parent_id             TEXT,
    params_hash           TEXT NOT NULL,
    data_hash             TEXT NOT NULL,
    judge_version         INTEGER NOT NULL,
    created_at            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    is_metrics_json       TEXT,
    wf_metrics_json       TEXT,
    cpcv_json             TEXT,
    dsr                   REAL,
    pbo                   REAL,
    gate_result           TEXT,
    gate_failures         TEXT,
    holdout_used          INTEGER NOT NULL DEFAULT 0,
    holdout_metrics_json  TEXT
);

CREATE TRIGGER IF NOT EXISTS trials_no_update
BEFORE UPDATE ON trials
BEGIN
    SELECT RAISE(ABORT, 'trials is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trials_no_delete
BEFORE DELETE ON trials
BEGIN
    SELECT RAISE(ABORT, 'trials is append-only');
END;

-- Létra-események (előléptetés, visszaléptetés, jóváhagyás) - szintén csak beszúrható
CREATE TABLE IF NOT EXISTS ladder_events (
    event_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_id TEXT NOT NULL,
    from_level  TEXT,
    to_level    TEXT NOT NULL,
    reason      TEXT NOT NULL,
    actor       TEXT NOT NULL CHECK (actor IN ('judge','human')),
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TRIGGER IF NOT EXISTS ladder_events_no_update
BEFORE UPDATE ON ladder_events
BEGIN
    SELECT RAISE(ABORT, 'ladder_events is append-only');
END;

CREATE TRIGGER IF NOT EXISTS ladder_events_no_delete
BEFORE DELETE ON ladder_events
BEGIN
    SELECT RAISE(ABORT, 'ladder_events is append-only');
END;

-- Napi futások naplója
CREATE TABLE IF NOT EXISTS runs (
    run_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL,
    step        TEXT,
    status      TEXT NOT NULL,
    message     TEXT,
    started_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    finished_at TEXT
);

-- Rezsimcímkék (1. fázistól töltődik)
CREATE TABLE IF NOT EXISTS regime_daily (
    date        TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    trend       TEXT NOT NULL CHECK (trend IN ('up','down','flat')),
    vol         TEXT NOT NULL CHECK (vol IN ('low','mid','high')),
    positioning TEXT NOT NULL CHECK (positioning IN ('crowded_long','crowded_short','neutral')),
    PRIMARY KEY (date, symbol)
);

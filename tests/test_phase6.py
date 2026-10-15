"""6. fázis: kutató (séma), fejlesztő (homokozó, worktree, ítélet), mutációk, létra, Telegram, L2-kapu."""

import datetime as dt
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from evolab.db import connect, init_db
from evolab.evolve import developer, ladder, mutations, researcher, sandbox
from evolab.judge import gates, ledger
from evolab.live import paper_runner as pr
from evolab.notify import commands
from evolab.strategy import registry
from test_phase3 import write_env

REPO = Path(__file__).resolve().parents[1]
TODAY = dt.date(2026, 10, 13)
LONG = ("A funding-ráta szélsőértékei a tőkeáttétes szereplők zsúfoltságát mutatják; amikor a zsúfolt oldal "
        "kényszerből zár, az ár a zsúfoltsággal szemben mozdul, és ezt a likvidációs kaszkád felerősíti. A szűrő "
        "ezért a trendjelet csak akkor engedi, ha a pozícionáltság nem szélsőséges, így a kifulladó szakaszok kimaradnak.")


def hyp(**over):
    h = {"family": "trend", "parent_strategy_id": "trend-ema-cross-4h-01", "mutation_type": "regime_condition",
         "change": "A trendjel csak magas volatilitású rezsimben aktív.", "rationale": LONG,
         "expected_regimes": ["up/high", "down/high"], "falsifier": "Ha magas vol mellett a PF 2x költségnél 1,0 alatt van.",
         "param_grid": {}}
    h.update(over)
    return h


# ---------------------------------------------------------------- kutató


def test_researcher_schema(cfg):
    """Hiányzó / rövid rationale és a többi szabálysértés -> elutasítva; a jók azonosítót kapnak."""
    raw = [
        hyp(),
        hyp(rationale="túl rövid indoklás"),
        {k: v for k, v in hyp().items() if k != "rationale"},
        hyp(rationale=LONG + " A holdout-időszakban is jól ment."),
        hyp(rationale=LONG + " Mert a visszateszt nagyon jó lett."),
        hyp(change="Emeljük a DSR-küszöböt a kapuban 0,9-re, mert túl szigorú."),
        hyp(expected_regimes=["bull/high"]),
        hyp(param_grid={"fast": [10, 20, 30], "slow": [100, 200, 300]}),
        hyp(family="ismeretlen"),
        hyp(parent_strategy_id="volbreak-squeeze-4h-04"),
    ]
    ok, rejected = researcher.validate(raw, cfg, TODAY, max_n=5)
    assert [h.id for h in ok] == ["H-2026-10-13-01"]
    reasons = " | ".join(r["reason"] for r in rejected)
    for needle in ("rationale", "holdout", "visszateszt", "kapu", "érvénytelen rezsim", "6 lehet",
                   "ismeretlen család", "más családba"):
        assert needle in reasons, needle
    assert len(rejected) == 9


def test_researcher_allows_mentioning_gates_but_not_changing_them(cfg):
    ok, rejected = researcher.validate([
        hyp(rationale=LONG + " A szülő a költségérzékenységi kapun bukik, a szűrő ezen javíthat."),
        hyp(change="A DSR-küszöb lazítása 0,9-re, mert a kapu túl szigorú a trendcsaládra."),
        hyp(change="A trendjel csak magas vol mellett; a kapuk és küszöbök változatlanok."),
    ], cfg, TODAY, max_n=5)
    assert len(ok) == 2 and len(rejected) == 1 and "kapu/küszöb" in rejected[0]["reason"]


def test_researcher_allows_pre_holdout_wording(cfg):
    ok, rejected = researcher.validate([
        hyp(falsifier="Cáfolt, ha a szülő visszatesztjében (a holdout előtti szakaszon) a PF 1,0 alatt van."),
        hyp(falsifier="Cáfolt, ha a holdout nélküli időszakban a kötések átlaga negatív."),
        hyp(rationale=LONG + " A holdout-időszakban is jól teljesített."),
    ], cfg, TODAY, max_n=5)
    assert len(ok) == 2 and rejected[0]["reason"] == "holdout-hivatkozás"


def test_researcher_requires_non_param_mutation(cfg):
    raw = [hyp(mutation_type="param", param_grid={"fast": [10, 30]}), hyp(mutation_type="param")]
    ok, rejected = researcher.validate(raw, cfg, TODAY)
    assert len(ok) == 1 and "nem-paraméter" in rejected[0]["reason"]


def test_researcher_run_saves_and_is_idempotent(cfg):
    calls = []

    def ask(prompt, schema):
        calls.append(prompt)
        assert "A mai napi riport" in prompt and "trend-ema-cross-4h-01" in prompt and "parent_signals" in prompt
        return {"hypotheses": [hyp(), hyp(rationale="rövid")]}

    ok, rejected = researcher.run(cfg, today=TODAY, ask=ask)
    assert len(ok) == 1 and len(rejected) == 1
    doc = (cfg.path("hypotheses") / "2026-10-13.yaml").read_text(encoding="utf-8")
    assert "H-2026-10-13-01" in doc and "rövid" in doc
    with connect(cfg.db_path) as conn:
        assert conn.execute("SELECT status FROM hypotheses").fetchone()["status"] == "new"
    again, _ = researcher.run(cfg, today=TODAY, ask=ask)
    assert len(calls) == 1 and [h.id for h in again] == ["H-2026-10-13-01"]


# ---------------------------------------------------------------- homokozó


def test_developer_sandbox():
    """Az evolve-ágon judge/ vagy config/judge.yaml (és sim/) módosítása elutasítva."""
    assert sandbox.check_changes(["src/evolab/strategy/families/trend/h2026101301_v1.py"]) == []
    for bad in ("src/evolab/judge/gates.py", "config/judge.yaml", "src/evolab/sim/engine.py", "db/schema.sql",
                "src/evolab/strategy/lib.py", "tests/test_x.py", "src/evolab/strategy/families/trend/notes.md"):
        assert sandbox.check_changes([bad]), bad


def _git(repo, *args, check=True):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=check)


def make_repo(root: Path) -> Path:
    """Ideiglenes git-repó a tesztkonfig gyökerében: családok, hook, .gitignore, `main` ág."""
    shutil.copytree(REPO / "src" / "evolab" / "strategy" / "families", root / "src/evolab/strategy/families")
    shutil.copytree(REPO / "ops" / "hooks", root / "ops/hooks")
    (root / ".gitignore").write_text("/data/\n/reports/\n/hypotheses/\n__pycache__/\n")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "teszt")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")
    return root


def test_precommit_hook_blocks_protected_files(tmp_path):
    repo = make_repo(tmp_path / "r")
    _git(repo, "config", "core.hooksPath", "ops/hooks")
    _git(repo, "checkout", "-q", "-b", "evolve/H-2026-10-13-01")
    (repo / "config").mkdir()
    (repo / "config" / "judge.yaml").write_text("version: 99\n")
    _git(repo, "add", "-A")
    r = _git(repo, "commit", "-m", "tiltott", check=False)
    assert r.returncode != 0 and "ELUTASÍTVA" in r.stderr
    _git(repo, "reset", "-q")
    (repo / "config" / "judge.yaml").unlink()
    f = repo / "src/evolab/strategy/families/trend/h2026101301_v1.py"
    f.write_text("x = 1\n")
    _git(repo, "add", "-A")
    assert _git(repo, "commit", "-q", "-m", "ok", check=False).returncode == 0


# ---------------------------------------------------------------- fejlesztő


def _saved_hypothesis(cfg, **over):
    ok, _ = researcher.validate([hyp(**over)], cfg, TODAY)
    researcher.save(cfg, ok, [], TODAY)
    return ok[0]


def _fake_llm(source_fn):
    def run(prompt, wt):
        target = wt / prompt.split("`")[1]   # a prompt első `...` része a célfájl
        source_fn(target, wt)
        return "kész"
    return run


def test_developer_writes_variants_judges_and_cleans_up(cfg, tmp_path):
    make_repo(cfg.root)
    today = write_env(cfg, n=3000, symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"))
    h = _saved_hypothesis(cfg, param_grid={"atr_stop": [2.0, 3.0], "atr_n": [10, 14]})  # 4 variáns: saját PBO

    def write(target, wt):
        target.write_text(mutations.condition_on_regime(h.parent_strategy_id, h.expected_regimes, h.id, h.rationale,
                                                        h.falsifier), encoding="utf-8")

    r = developer.develop(cfg, h, today=today, run_llm=_fake_llm(write), merge=False)
    assert r.status in ("developed_pass", "developed_fail"), r.message
    assert r.variants == [f"trend-h2026101301-v{k}" for k in range(1, 5)]
    assert set(r.verdicts) == set(r.variants)
    files = _git(cfg.root, "show", "--name-only", "--format=", "evolve/H-2026-10-13-01").stdout.split()
    assert files == [f"src/evolab/strategy/families/trend/h2026101301_v{k}.py" for k in range(1, 5)]
    assert not (cfg.path("data") / "worktrees" / h.id).exists()  # a worktree eltakarítva
    with connect(cfg.db_path) as conn:
        assert conn.execute("SELECT status FROM hypotheses").fetchone()["status"] == r.status
        rows = conn.execute("SELECT gate_result FROM trials WHERE strategy_id LIKE 'trend-h2026101301-%' "
                            "AND gate_result IN ('pass','fail')").fetchall()
    assert len(rows) == 4


def test_developer_rejects_write_outside_families(cfg):
    make_repo(cfg.root)
    h = _saved_hypothesis(cfg)

    def write(target, wt):
        target.write_text(mutations.condition_on_regime(h.parent_strategy_id, h.expected_regimes, h.id, h.rationale,
                                                        h.falsifier), encoding="utf-8")
        (wt / "src/evolab/judge").mkdir(parents=True, exist_ok=True)
        (wt / "src/evolab/judge/gates.py").write_text("# kapu kikapcsolva\n")

    r = developer.develop(cfg, h, today=TODAY, run_llm=_fake_llm(write), merge=False)
    assert r.status == "rejected" and "védett fájl" in r.message
    assert _git(cfg.root, "log", "--oneline", "evolve/H-2026-10-13-01").stdout.count("\n") == 1  # csak az init


def test_developer_rejects_lookahead(cfg):
    make_repo(cfg.root)
    h = _saved_hypothesis(cfg)
    src = (REPO / "src/evolab/strategy/families/trend/ema_cross_4h_01.py").read_text(encoding="utf-8")

    def write(target, wt):
        cheat = src.replace('    c = d["close"]\n', '    c = d["close"].shift(-1).ffill()  # csalás: holnapi ár\n', 1)
        cheat = mutations.set_header_field(cheat, "hypothesis_id", h.id)
        target.write_text(cheat, encoding="utf-8")

    r = developer.develop(cfg, h, today=TODAY, run_llm=_fake_llm(write), merge=False)
    assert r.status == "rejected" and "jövőbe látás" in r.message


def test_param_mutation_needs_no_llm(cfg):
    make_repo(cfg.root)
    today = write_env(cfg, n=3000, symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"))
    h = _saved_hypothesis(cfg, mutation_type="param", param_grid={"fast": [15, 25], "slow": [80, 120]})
    r = developer.develop(cfg, h, today=today, run_llm=lambda *a: pytest.fail("LLM nem kellett volna"),
                          merge=False)
    assert r.status in ("developed_pass", "developed_fail") and len(r.variants) == 4


def test_merge_only_when_clean_on_main(tmp_path):
    repo = make_repo(tmp_path / "r")
    _git(repo, "checkout", "-q", "-b", "evolve/H-x")
    (repo / "src/evolab/strategy/families/trend/hx_v1.py").write_text("x = 1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "v")
    _git(repo, "checkout", "-q", "main")
    (repo / "src/evolab/strategy/families/trend/ema_cross_4h_01.py").write_text("piszkos\n")
    assert developer._merge(repo, "evolve/H-x", "main") is False
    _git(repo, "checkout", "--", ".")
    assert developer._merge(repo, "evolve/H-x", "main") is True
    assert (repo / "src/evolab/strategy/families/trend/hx_v1.py").exists()


# ---------------------------------------------------------------- mutációk


@pytest.mark.parametrize("make", [
    lambda: mutations.param_variant("trend-ema-cross-4h-01", {"fast": 15}, "H-2026-10-13-01", LONG, ["up/high"], "f" * 30),
    lambda: mutations.condition_on_regime("volbreak-squeeze-4h-04", ["up/low", "flat/low"], "H-2026-10-13-01", LONG,
                                          "f" * 30),
    lambda: mutations.crossover("trend-ema-cross-4h-02", "trend-donchian-4h-01", "H-2026-10-13-01", LONG,
                                ["up/high"], "f" * 30),
])
def test_mutation_files_load_and_pass_lookahead(tmp_path, make):
    d = tmp_path / "trend" if "squeeze" not in make.__code__.co_consts.__repr__() else tmp_path / "volbreak"
    d.mkdir(parents=True)
    f = d / "h2026101301_v1.py"
    f.write_text(make(), encoding="utf-8")
    s = registry.load_file(f)
    assert s.meta.hypothesis_id == "H-2026-10-13-01" and s.meta.parent_id
    ok, why = sandbox.lookahead_ok(s)
    assert ok, why


# ---------------------------------------------------------------- létra, Telegram, L2


def _strategy(cfg, sid, level="L0"):
    init_db(cfg)
    with connect(cfg.db_path) as conn:
        conn.execute("INSERT INTO strategies(strategy_id, family, timeframe, file_path, level) VALUES (?, ?, '4h', 'x', ?)",
                     (sid, sid.split("-")[0], level))


def _verdict(cfg, sid, result, judge_version=None):
    ledger.record(cfg, {"trial_id": f"t-{sid}-{result}-{dt.datetime.now().timestamp()}", "strategy_id": sid,
                        "family": sid.split("-")[0], "params_hash": "p", "data_hash": "d", "dsr": 0.97, "pbo": 0.1,
                        "gate_result": result, "judge_version": judge_version,
                        "is_metrics_json": json.dumps({"trades": 150, "profit_factor": 1.5, "pf_2x": 1.35,
                                                       "max_dd": 0.1, "regime_ev": {}}),
                        "wf_metrics_json": json.dumps({"oos_is_ratio": 0.8}), "gate_failures": json.dumps([])})


def test_ladder_l1_waitlist_approve_reject_expiry(cfg):
    for sid in ("trend-ema-cross-4h-01", "trend-ema-cross-4h-02", "trend-ema-cross-4h-03"):
        _strategy(cfg, sid)
        _verdict(cfg, sid, "pass")
    res = ladder.apply(cfg)
    assert sorted(res["waiting"]) == ["trend-ema-cross-4h-01", "trend-ema-cross-4h-02", "trend-ema-cross-4h-03"]
    assert "L1 -> L2" in ladder.approve(cfg, "trend-ema-cross-4h-01")
    assert ladder.level(cfg, "trend-ema-cross-4h-01") == "L2"
    ladder.reject(cfg, "trend-ema-cross-4h-02", "túl kevés kötés")
    assert ladder.level(cfg, "trend-ema-cross-4h-02") == "L0"
    with pytest.raises(ladder.LadderError, match="paper-ítélet"):
        ladder.approve(cfg, "trend-ema-cross-4h-01")               # L2 -> L3 csak l2_pass után
    later = dt.datetime.now(dt.UTC) + dt.timedelta(days=15)
    assert ("trend-ema-cross-4h-03", "L1", "L0") in ladder.apply(cfg, now=later)["changes"]
    with connect(cfg.db_path) as conn:
        actors = [r["actor"] for r in conn.execute("SELECT actor FROM ladder_events ORDER BY event_id")]
        with pytest.raises(Exception, match="append-only"):
            conn.execute("DELETE FROM ladder_events")
    assert actors.count("human") == 2


def test_ladder_demotion_removes_from_paper_roster(cfg):
    sid = "trend-ema-cross-4h-01"
    _strategy(cfg, sid, "L2")
    roster = pr.ensure_roster(cfg, now=0)
    assert roster["strategies"][sid]["mode"] == "L2"
    ladder.apply(cfg, paper_verdicts=[{"strategy_id": sid, "result": "l2_demote", "reasons": ["DD-arány 2.0 > 1.5"]}])
    assert ladder.level(cfg, sid) == "retired"
    roster = pr.ensure_roster(cfg, now=0)
    assert sid not in roster["strategies"] and sid in roster["ended"]


def test_check_l2_gate(cfg):
    base = {"trades": 250, "profit_factor": 1.3, "max_dd": 0.08,
            "regime_ev": {"up/high": {"trades": 30, "ev": 1.0}, "down/high": {"trades": 20, "ev": 1.0}}}
    assert gates.check_l2(base, 0.1, cfg.judge)[0] == "l2_pass"
    assert gates.check_l2({**base, "trades": 50}, 0.1, cfg.judge)[0] == "l2_hold"
    assert gates.check_l2({**base, "trades": 50, "max_dd": 0.2}, 0.1, cfg.judge)[0] == "l2_demote"  # DD-arány 2
    assert gates.check_l2({**base, "profit_factor": 1.05}, 0.1, cfg.judge)[0] == "l2_demote"
    assert gates.check_l2({**base, "profit_factor": 1.15}, 0.1, cfg.judge)[0] == "l2_hold"


def test_telegram_commands_only_from_own_chat(cfg, monkeypatch):
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    sid = "trend-ema-cross-4h-01"
    _strategy(cfg, sid)
    _verdict(cfg, sid, "pass")
    ladder.apply(cfg)
    sent = []
    updates = [
        {"update_id": 10, "message": {"chat": {"id": 99}, "text": f"/approve {sid}"}},   # idegen chat
        {"update_id": 11, "message": {"chat": {"id": 42}, "text": "/waiting"}},
        {"update_id": 12, "message": {"chat": {"id": 42}, "text": f"/approve {sid}"}},
        {"update_id": 13, "message": {"chat": {"id": 42}, "text": "szia"}},
    ]
    done = commands.poll(cfg, send=sent.append, fetch=lambda off: [u for u in updates if off is None or u["update_id"] >= off])
    assert [c for c, _ in done] == ["/waiting", f"/approve {sid}"]
    assert sid in sent[0] and "L1 -> L2" in sent[1]
    assert ladder.level(cfg, sid) == "L2"
    assert commands.poll(cfg, send=sent.append, fetch=lambda off: [u for u in updates if u["update_id"] >= off]) == []


def test_daily_streak_counts_only_full_real_runs(cfg):
    from evolab.evolve.health import daily_streak

    init_db(cfg)
    steps = "data,judge,report,researcher,developer,ladder"
    rows = [("2026-10-08", steps, "ok", "- data: még nincs megvalósítva"),     # csonk korszak: nem számít
            ("2026-10-09", steps, "ok", "rendben"), ("2026-10-10", steps, "error", "hiba"),
            ("2026-10-11", steps, "ok", "rendben"), ("2026-10-12", "researcher", "ok", "kézi"),
            ("2026-10-12", steps, "warn", "Telegram hiba"), ("2026-10-13", steps, "ok", "rendben")]
    with connect(cfg.db_path) as conn:
        for day, step, status, msg in rows:
            conn.execute("INSERT INTO runs(kind, step, status, message, started_at) VALUES ('daily', ?, ?, ?, ?)",
                         (step, status, msg, f"{day}T00:00:05Z"))
    n, _ = daily_streak(cfg, today=dt.date(2026, 10, 13))
    assert n == 3  # 10-11, 10-12 (warn is jó), 10-13; a 10-10-i hiba megszakítja

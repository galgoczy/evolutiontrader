"""Fejlesztő (docs/02-specifikacio.md 6.3): hipotézisből variánsfájl(ok), homokozóban, bírói ítélettel.

Hipotézisenként:
1. külön git worktree `evolve/<hipotézis>` ágon (`data/worktrees/`), hogy a futó launchd-feladatok
   munkakönyvtára érintetlen maradjon;
2. a variánsfájl: `param` mutációnál determinisztikusan (`mutations.param_variant`), minden más
   típusnál Claude Code fej nélkül (`claude -p`, csak Read/Write/Edit/Glob/Grep eszközzel);
3. homokozó: csak `strategy/families/` alatti új .py fájl; registry-ellenőrzés; jövőbe-látás próba;
4. a `param_grid` kombinációi (legfeljebb 6) külön variánsfájlokba, commit az ágra (pre-commit hook véd);
5. L1-ítélet minden variánsra (`judge.evaluate.evaluate_l1`, mind a ledgerbe);
6. ha legalább egy variáns átment: az ág merge-ölődik a helyi `main`-be (csak tiszta, `main`-en álló
   munkakönyvtárnál; különben az ág megmarad kézi merge-re). A STOP kapcsoló ezt a lépést kihagyja.
"""

from __future__ import annotations

import datetime as dt
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from string import Template

import yaml

from evolab.config import Config
from evolab.db import connect
from evolab.evolve import llm, mutations, sandbox
from evolab.evolve.llm import template_text
from evolab.evolve.researcher import Hypothesis, _lib_api, todays
from evolab.judge.evaluate import evaluate_l1
from evolab.strategy import registry

PROMPT = Path(__file__).parent / "prompts" / "developer.md"
FAMILIES_REL = Path("src/evolab/strategy/families")


@dataclass
class DevResult:
    hypothesis_id: str
    status: str                      # developed_pass | developed_fail | rejected | error
    variants: list[str] = field(default_factory=list)
    verdicts: dict[str, str] = field(default_factory=dict)
    merged: bool = False
    message: str = ""


def git(repo: Path, *args: str, check: bool = True) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=check).stdout.strip()


def ensure_hook(repo: Path) -> None:
    """A homokozó pre-commit hook bekapcsolása a repóban (minden worktree-re érvényes)."""
    if git(repo, "config", "--get", "core.hooksPath", check=False) != "ops/hooks":
        git(repo, "config", "core.hooksPath", "ops/hooks")


def base_name(h: Hypothesis) -> str:
    """Fájlnév-tő: h<ééééhhnn><sorszám>, pl. h2026101301 -> azonosító trend-h2026101301-v1."""
    date, nn = h.id[2:12].replace("-", ""), h.id[-2:]
    return f"h{date}{nn}"


def _example(family: str, parent_id: str | None) -> str:
    files = registry.discover()
    sid = parent_id if parent_id in files else next((s for s in files if s.startswith(family + "-")), next(iter(files)))
    return files[sid].read_text(encoding="utf-8")


def build_prompt(cfg: Config, h: Hypothesis, target_rel: str) -> str:
    fam = cfg.families["families"][h.family]
    return Template(template_text(PROMPT)).substitute(
        target=target_rel, family=h.family, hypothesis_id=h.id,
        parent_line=f"parent_id: {h.parent_strategy_id}," if h.parent_strategy_id else "",
        timeframes=", ".join(fam["timeframes"]), grid_keys=", ".join(h.param_grid) or "(nincs)",
        lib_api=_lib_api(), example=_example(h.family, h.parent_strategy_id),
        hypothesis=yaml.safe_dump(h.model_dump(), allow_unicode=True, sort_keys=False))


def _set_status(cfg: Config, hid: str, status: str) -> None:
    with connect(cfg.db_path) as conn:
        conn.execute("UPDATE hypotheses SET status = ? WHERE hypothesis_id = ?", (status, hid))


def write_first_variant(cfg: Config, h: Hypothesis, wt: Path, target: Path, run_llm=None) -> str:
    """Az első variánsfájl megírása a worktree-ben. Visszaad: rövid leírás."""
    if h.mutation_type == "param" and h.parent_strategy_id:
        first = h.combos()[0]
        target.write_text(mutations.param_variant(h.parent_strategy_id, first, h.id, h.rationale,
                                                  h.expected_regimes, h.falsifier), encoding="utf-8")
        return "param-mutáció determinisztikusan (LLM nélkül)"
    prompt = build_prompt(cfg, h, str(target.relative_to(wt)))
    if run_llm is not None:
        return run_llm(prompt, wt)
    res = llm.run_cli(prompt, cfg.lab["developer"]["model"], cwd=wt,
                      allowed_tools=["Read", "Write", "Edit", "Glob", "Grep"],
                      disallowed_tools=["Bash", "WebFetch", "WebSearch", "NotebookEdit"],
                      permission_mode="acceptEdits", timeout_s=int(cfg.lab["developer"]["timeout_s"]))
    return str(res.output)[:300]


def develop(cfg: Config, h: Hypothesis, repo: Path | None = None, today: dt.date | None = None,
            run_llm=None, merge: bool = True) -> DevResult:
    repo = repo or cfg.root
    ensure_hook(repo)
    branch = f"evolve/{h.id}"
    wt = cfg.path("data") / "worktrees" / h.id
    out = DevResult(h.id, "error")
    if git(repo, "branch", "--list", branch):
        out.status, out.message = "rejected", f"az ág már létezik: {branch}"
        return out
    git(repo, "worktree", "add", "-b", branch, str(wt), cfg.lab["developer"]["base_branch"])
    try:
        stem = base_name(h)
        fam_dir = wt / FAMILIES_REL / h.family
        target = fam_dir / f"{stem}_v1.py"
        out.message = write_first_variant(cfg, h, wt, target, run_llm)
        # --- homokozó: mi változott a worktree-ben
        changed = [ln[3:] for ln in git(wt, "status", "--porcelain", "--untracked-files=all").splitlines()]
        bad = sandbox.check_changes(changed)
        if bad or not target.exists():
            out.status = "rejected"
            out.message = "; ".join(bad) or f"a fejlesztő nem hozta létre: {target.relative_to(wt)}"
            return out
        strat = registry.load_file(target)
        if strat.meta.header.get("hypothesis_id") != h.id or strat.meta.family != h.family:
            raise registry.StrategyRejected("a fejléc hypothesis_id-ja vagy családja nem egyezik")
        missing = [k for k in h.param_grid if k not in strat.meta.params]
        if missing:
            raise registry.StrategyRejected(f"a PARAMS-ból hiányzik a param_grid kulcsa: {missing}")
        ok, why = sandbox.lookahead_ok(strat)
        if not ok:
            out.status, out.message = "rejected", why
            return out
        # --- param_grid -> további variánsok
        src = target.read_text(encoding="utf-8")
        for k, combo in enumerate(h.combos()[1:], start=2):
            (fam_dir / f"{stem}_v{k}.py").write_text(
                mutations.with_params(src, {**strat.meta.params, **combo}), encoding="utf-8")
        files = sorted(fam_dir.glob(f"{stem}_v*.py"))
        out.variants = [registry.strategy_id(f) for f in files]
        git(wt, "add", *[str(f.relative_to(wt)) for f in files])
        git(wt, "commit", "-q", "-m", f"{h.id}: {h.family} {h.mutation_type} ({len(files)} variáns)\n\n{h.change}")
        bad = sandbox.check_branch(repo, branch, cfg.lab["developer"]["base_branch"])
        if bad:
            out.status, out.message = "rejected", "; ".join(bad)
            return out
        # --- L1-ítélet minden variánsra (a worktree családmappájából)
        for sid in out.variants:
            ev = evaluate_l1(cfg, sid, today=today, strategies_root=wt / FAMILIES_REL)
            out.verdicts[sid] = ev["gate_result"]
        passed = any(v == "pass" for v in out.verdicts.values())
        out.status = "developed_pass" if passed else "developed_fail"
        if passed and merge:
            out.merged = _merge(repo, branch, cfg.lab["developer"]["base_branch"])
            if not out.merged:
                out.message += " | kézi merge kell (a munkakönyvtár nem tiszta vagy nem a main-en áll)"
        return out
    except registry.StrategyRejected as e:
        out.status, out.message = "rejected", str(e)
        return out
    except Exception as e:  # egy hipotézis hibája ne állítsa le a napi futást
        out.status, out.message = "error", f"{type(e).__name__}: {e}"
        return out
    finally:
        git(repo, "worktree", "remove", "--force", str(wt), check=False)
        _set_status(cfg, h.id, out.status)


def _merge(repo: Path, branch: str, base: str) -> bool:
    if git(repo, "rev-parse", "--abbrev-ref", "HEAD") != base or git(repo, "status", "--porcelain", "--untracked-files=no"):
        return False
    git(repo, "merge", "--no-ff", "-q", "-m", f"Merge {branch} (L1 átment)", branch)
    return True


def run(cfg: Config, today: dt.date | None = None, run_llm=None, log=print) -> list[DevResult]:
    """A napi fejlesztői lépés: a mai, még nem fejlesztett hipotézisek."""
    today = today or dt.date.today()
    if cfg.stop_file.exists():
        log("STOP kapcsoló aktív: fejlesztő kihagyva.")
        return []
    with connect(cfg.db_path) as conn:
        done = {r["hypothesis_id"] for r in conn.execute("SELECT hypothesis_id FROM hypotheses WHERE status != 'new'")}
    results = []
    for h in todays(cfg, today):
        if h.id in done:
            continue
        r = develop(cfg, h, today=today, run_llm=run_llm)
        results.append(r)
        log(f"  {h.id} [{h.family}/{h.mutation_type}] {r.status}: {', '.join(f'{k}={v}' for k, v in r.verdicts.items())}"
            f"{' | merge-ölve' if r.merged else ''} {r.message[:160]}")
    return results


def summary(results: list[DevResult]) -> str:
    if not results:
        return "nincs új hipotézis"
    parts = []
    for r in results:
        n_pass = sum(v == "pass" for v in r.verdicts.values())
        parts.append(f"{r.hypothesis_id}: {r.status} ({n_pass}/{len(r.variants)} L1)" + (" merge" if r.merged else ""))
    return "; ".join(parts)


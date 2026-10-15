"""Kutató (docs/02-specifikacio.md 6.2): napi 2-3 hipotézis Claude-dal, pydantic-kal ellenőrizve.

Bemenet: a napi riport, az elmúlt 14 nap hipotézisei és sorsuk, a `families.yaml`, a meglévő variánsok
és a kísérletszám-számláló. Kimenet: `hypotheses/YYYY-MM-DD.yaml` + `hypotheses` tábla (status `new`).
Az érvénytelen hipotézis elutasítva (okkal naplózva), a többi megy tovább a fejlesztőhöz.
"""

from __future__ import annotations

import datetime as dt
import inspect
import itertools
import json
import re
from pathlib import Path
from string import Template
from typing import Literal

import pandas as pd
import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator

from evolab.config import Config
from evolab.db import connect, init_db
from evolab.evolve import llm
from evolab.evolve.llm import template_text
from evolab.strategy import lib, registry

PROMPT = Path(__file__).parent / "prompts" / "researcher.md"
MutationType = Literal["filter_add", "param", "crossover", "regime_condition", "rewrite"]
REGIME_RE = re.compile(r"^(up|down|flat)/(low|mid|high)$")
# szabálysértések a szövegben (spec 6.2): holdout/paper-hivatkozás, kapu/küszöb-javaslat, „jó a visszateszt”
FORBIDDEN = [
    # a „holdout előtti / nélküli szakasz” megnevezése szabályos (épp a holdoutot zárja ki), minden más tilos
    (re.compile(r"holdout(?![\s-]*(?:előtt|nélkül|kizár|-ablakon\s+kívül))", re.I), "holdout-hivatkozás"),
    (re.compile(r"\bpaper\w*", re.I), "paper-időszakra hivatkozás"),
    # csak a kapu/küszöb MÓDOSÍTÁSÁNAK javaslata tilos; a kapura mint mércére hivatkozni szabad
    (re.compile(r"judge\.yaml|\b(?:kapu|küszöb)\w*[^.]{0,60}?\b(?:módosít|csökkent|emel|lazít|változtat|kikapcsol"
                r"|átír|megszüntet|töröl)\w*|\b(?:módosít|csökkent|emel|lazít|változtat|kikapcsol|átír|megszüntet|töröl)"
                r"\w*[^.]{0,60}?\b(?:kapu|küszöb|bírói)\w*", re.I), "kapu/küszöb módosítása"),
    (re.compile(r"visszateszt\w*\s+(?:\w+\s+){0,3}(jó|szép|kiváló|nyereséges|pozitív)|backtest", re.I),
     "„jó a visszateszt” indoklás"),
]


class Hypothesis(BaseModel):
    id: str = ""
    family: str
    parent_strategy_id: str | None = None
    mutation_type: MutationType
    change: str = Field(min_length=20)
    rationale: str = Field(min_length=200)
    expected_regimes: list[str] = Field(min_length=1)
    falsifier: str = Field(min_length=20)
    param_grid: dict[str, list] = Field(default_factory=dict)

    @field_validator("expected_regimes")
    @classmethod
    def _regimes(cls, v: list[str]) -> list[str]:
        bad = [r for r in v if not REGIME_RE.match(r)]
        if bad:
            raise ValueError(f"érvénytelen rezsim: {bad}")
        return v

    @field_validator("param_grid")
    @classmethod
    def _grid(cls, v: dict[str, list]) -> dict[str, list]:
        n = 1
        for vals in v.values():
            if not isinstance(vals, list) or not vals:
                raise ValueError("a param_grid értékei nem üres listák")
            n *= len(vals)
        if n > 6:
            raise ValueError(f"a param_grid {n} kombináció, legfeljebb 6 lehet")
        return v

    def combos(self) -> list[dict]:
        if not self.param_grid:
            return [{}]
        keys = list(self.param_grid)
        return [dict(zip(keys, vals)) for vals in itertools.product(*self.param_grid.values())]


JSON_SCHEMA = {
    "type": "object",
    "properties": {"hypotheses": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "family": {"type": "string"},
            "parent_strategy_id": {"type": ["string", "null"]},
            "mutation_type": {"type": "string", "enum": list(MutationType.__args__)},
            "change": {"type": "string"},
            "rationale": {"type": "string"},
            "expected_regimes": {"type": "array", "items": {"type": "string"}},
            "falsifier": {"type": "string"},
            "param_grid": {"type": "object", "additionalProperties": {"type": "array"}},
        },
        "required": ["family", "mutation_type", "change", "rationale", "expected_regimes", "falsifier"],
    }}},
    "required": ["hypotheses"],
}


def validate(raw: list[dict], cfg: Config, today: dt.date, known: dict[str, str] | None = None,
             max_n: int | None = None) -> tuple[list[Hypothesis], list[dict]]:
    """Visszaadja (elfogadott hipotézisek azonosítóval, elutasítottak okkal).

    `known`: meglévő variáns -> család. A napi „legalább 1 nem-paraméter mutáció” szabály: ha minden
    elfogadott hipotézis `param`, csak az első marad, a többi elutasítva.
    """
    families = set(cfg.families["families"])
    known = known if known is not None else {sid: sid.split("-")[0] for sid in registry.discover()}
    max_n = max_n or int(cfg.lab["researcher"]["max_hypotheses_per_day"])
    ok: list[Hypothesis] = []
    rejected: list[dict] = []
    for item in raw:
        try:
            h = Hypothesis.model_validate(item)
        except ValidationError as e:
            rejected.append({"item": item, "reason": "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}"
                                                                for x in e.errors())})
            continue
        reasons = []
        if h.family not in families:
            reasons.append(f"ismeretlen család: {h.family}")
        if h.parent_strategy_id and known.get(h.parent_strategy_id) != h.family:
            reasons.append(f"ismeretlen vagy más családba tartozó szülő: {h.parent_strategy_id}")
        text = " ".join([h.change, h.rationale, h.falsifier])
        reasons += [why for rx, why in FORBIDDEN if rx.search(text)]
        if len(ok) >= max_n:
            reasons.append(f"napi legfeljebb {max_n} hipotézis")
        if reasons:
            rejected.append({"item": item, "reason": "; ".join(reasons)})
        else:
            ok.append(h)
    if ok and all(h.mutation_type == "param" for h in ok):
        rejected += [{"item": h.model_dump(), "reason": "nincs nem-paraméter mutáció a napi készletben"} for h in ok[1:]]
        ok = ok[:1]
    for k, h in enumerate(ok, 1):
        h.id = f"H-{today.isoformat()}-{k:02d}"
    return ok, rejected


# ---------------------------------------------------------------- prompt


def _lib_api() -> str:
    lines = []
    for name, fn in inspect.getmembers(lib, inspect.isfunction):
        if fn.__module__ == lib.__name__ and not name.startswith("_"):
            doc = (inspect.getdoc(fn) or "").split("\n")[0]
            lines.append(f"- `{name}{inspect.signature(fn)}`: {doc}")
    return "\n".join(lines)


def _strategies() -> str:
    lines = []
    for sid, path in registry.discover().items():
        try:
            m = registry.load_file(path).meta
            lines.append(f"- {sid} ({m.family}, {m.timeframe}): {json.dumps(m.params, ensure_ascii=False)}")
        except registry.StrategyRejected:
            continue
    return "\n".join(lines)


def history(cfg: Config, days: int = 14, today: dt.date | None = None) -> pd.DataFrame:
    """Az elmúlt `days` nap hipotézisei és sorsuk (a variánsaik legutolsó L1-ítéletéből)."""
    if not cfg.db_path.exists():
        return pd.DataFrame()
    today = today or dt.date.today()
    since = (today - dt.timedelta(days=days)).isoformat()
    with connect(cfg.db_path) as conn:
        h = pd.read_sql_query("SELECT * FROM hypotheses WHERE created_at >= ? ORDER BY created_at", conn, params=(since,))
        t = pd.read_sql_query("SELECT hypothesis_id, strategy_id, gate_result, gate_failures, created_at FROM trials "
                              "WHERE gate_result IN ('pass', 'fail') AND hypothesis_id IS NOT NULL ORDER BY created_at",
                              conn)
    if h.empty:
        return h
    last = t.groupby("strategy_id").tail(1)
    fate = last.groupby("hypothesis_id").apply(
        lambda g: f"{int((g['gate_result'] == 'pass').sum())}/{len(g)} variáns L1-en át; "
                  f"jellemző bukás: {(json.loads(g['gate_failures'].iloc[0] or '[]') or ['-'])[0]}",
        include_groups=False) if not last.empty else pd.Series(dtype=str)
    h["fate"] = h["hypothesis_id"].map(fate).fillna(h["status"])
    return h


def build_prompt(cfg: Config, today: dt.date, report_md: str, trial_counts: list[dict]) -> str:
    hist = history(cfg, 14, today)
    hist_txt = "\n".join(f"- {r.hypothesis_id} [{r.family}, {r.mutation_type}] {r.change} → {r.fate}"
                         for r in hist.itertuples()) or "(még nincs)"
    fam_txt = yaml.safe_dump(cfg.families["families"], allow_unicode=True, sort_keys=False)
    tc_txt = "\n".join(f"- {t['family']}: {t['configs']} konfiguráció, hatékony N {t['n_eff']}, "
                       f"SR0 évesítve {t['sr0_annual']:.2f}" for t in trial_counts) or "-"
    return Template(template_text(PROMPT)).substitute(
        date=today.isoformat(), n_max=cfg.lab["researcher"]["max_hypotheses_per_day"], families=fam_txt,
        strategies=_strategies(), lib_api=_lib_api(), history=hist_txt, trial_counts=tc_txt, report=report_md)


# ---------------------------------------------------------------- mentés, futtatás


def save(cfg: Config, hyps: list[Hypothesis], rejected: list[dict], today: dt.date, meta: dict | None = None) -> Path:
    init_db(cfg)
    with connect(cfg.db_path) as conn:
        for h in hyps:
            conn.execute(
                "INSERT OR REPLACE INTO hypotheses(hypothesis_id, family, parent_strategy_id, mutation_type, change, "
                "rationale, expected_regimes, falsifier, param_grid_json, status) VALUES (?,?,?,?,?,?,?,?,?, 'new')",
                (h.id, h.family, h.parent_strategy_id, h.mutation_type, h.change, h.rationale,
                 json.dumps(h.expected_regimes), h.falsifier, json.dumps(h.param_grid)))
    out = cfg.path("hypotheses") / f"{today.isoformat()}.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    doc = {"date": today.isoformat(), **(meta or {}), "hypotheses": [h.model_dump() for h in hyps],
           "rejected": rejected}
    out.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return out


def todays(cfg: Config, today: dt.date) -> list[Hypothesis]:
    if not cfg.db_path.exists():
        return []
    with connect(cfg.db_path) as conn:
        rows = conn.execute("SELECT * FROM hypotheses WHERE hypothesis_id LIKE ? ORDER BY hypothesis_id",
                            (f"H-{today.isoformat()}-%",)).fetchall()
    return [Hypothesis(id=r["hypothesis_id"], family=r["family"], parent_strategy_id=r["parent_strategy_id"],
                       mutation_type=r["mutation_type"], change=r["change"], rationale=r["rationale"],
                       expected_regimes=json.loads(r["expected_regimes"]), falsifier=r["falsifier"],
                       param_grid=json.loads(r["param_grid_json"] or "{}")) for r in rows]


def run(cfg: Config, today: dt.date | None = None, ask=None) -> tuple[list[Hypothesis], list[dict]]:
    """A napi kutatói lépés. `ask(prompt, schema) -> dict` cserélhető (tesztben ál-LLM)."""
    from evolab.report import daily

    today = today or dt.date.today()
    existing = todays(cfg, today)
    if existing:  # idempotens: a napi kutatói kör egyszer fut (újrafuttatáskor a meglévőt adja)
        return existing, []
    report_path = cfg.path("reports") / f"{today.isoformat()}.md"
    r = daily.build(cfg, today)
    report_md = report_path.read_text(encoding="utf-8") if report_path.exists() else daily.to_markdown(r)
    prompt = build_prompt(cfg, today, report_md, r["trial_counts"])
    model = cfg.lab["researcher"]["model"]
    if ask is None:
        res = llm.run_cli(prompt, model, schema=JSON_SCHEMA, disallowed_tools=["Bash", "Write", "Edit", "WebFetch"],
                          timeout_s=900)
        out, meta = res.output, {"model": model, "cost_usd": res.cost_usd}
    else:
        out, meta = ask(prompt, JSON_SCHEMA), {"model": "teszt"}
    raw = out.get("hypotheses", []) if isinstance(out, dict) else []
    ok, rejected = validate(raw, cfg, today)
    save(cfg, ok, rejected, today, meta)
    return ok, rejected

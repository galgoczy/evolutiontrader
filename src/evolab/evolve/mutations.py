"""Determinisztikus mutációs operátorok (docs/02-specifikacio.md 6.5).

Nem az LLM írja őket: a fejlesztő (vagy a `param` típusú hipotézisnél maga a rendszer) ezekkel állít
elő új variánsfájlt. Mindegyik egy teljes, önálló stratégiafájl szövegét adja vissza YAML fejléccel;
a jelszintű logika a `strategy/lib.py`-ban van (`parent_signals`, `condition`, `block_direction`,
`crossover`). A `rewrite` az egyetlen típus, ahol az LLM szabadon ír kódot a sablon felületén belül.
"""

from __future__ import annotations

import re
import textwrap

from evolab.judge.evaluate import perturbations
from evolab.strategy import registry


def _header(family: str, hypothesis_id: str, parent_id: str | None, hypothesis: str, regimes: list[str],
            falsifier: str) -> str:
    def wrap(t: str) -> str:
        return textwrap.fill(" ".join(t.split()), 98, initial_indent="  ", subsequent_indent="  ")

    return (f'"""\nfamily: {family}\nhypothesis_id: {hypothesis_id}\n'
            + (f"parent_id: {parent_id}\n" if parent_id else "")
            + f"hypothesis: >\n{wrap(hypothesis)}\nexpected_regimes: [{', '.join(regimes)}]\n"
            f"falsifier: >\n{wrap(falsifier)}\n\"\"\"\n")


def with_params(source: str, params: dict) -> str:
    """Egy variánsfájl szövege más `PARAMS`-szal (a többi változatlan)."""
    new, n = re.subn(r"^PARAMS = .*$", f"PARAMS = {params!r}", source, count=1, flags=re.M)
    if n != 1:
        raise ValueError("a fájlban nincs egysoros PARAMS = {...} definíció")
    return new


def set_header_field(source: str, key: str, value: str) -> str:
    """Egy egysoros fejlécmező (pl. hypothesis_id) beállítása vagy felvétele a `family:` sor után."""
    if re.search(rf"^{key}: .*$", source, flags=re.M):
        return re.sub(rf"^{key}: .*$", f"{key}: {value}", source, count=1, flags=re.M)
    return re.sub(r"^(family: .*)$", rf"\1\n{key}: {value}", source, count=1, flags=re.M)


def perturb_params(strategy_id: str, pct: float) -> dict[str, dict]:
    """A szülő paramétereinek ±pct% változatai (név -> teljes paraméterkészlet)."""
    return perturbations(registry.load(strategy_id).meta.params, pct)


def param_variant(parent_id: str, params: dict, hypothesis_id: str, hypothesis: str, regimes: list[str],
                  falsifier: str) -> str:
    """`param` mutáció: a szülő fájlja új paraméterekkel és új fejléccel."""
    parent = registry.load(parent_id)
    src = parent.path.read_text(encoding="utf-8")
    body = src[src.index('"""', 3) + 3:]  # a régi fejléc utáni rész
    return _header(parent.meta.family, hypothesis_id, parent_id, hypothesis, regimes, falsifier) + \
        with_params(body, {**parent.meta.params, **params})


def condition_on_regime(parent_id: str, labels: list[str], hypothesis_id: str, hypothesis: str,
                        falsifier: str, params: dict | None = None) -> str:
    """`regime_condition`: a szülő jele csak a megadott trend/vol címkék alatt aktív. A szülő numerikus
    paraméterei a saját `PARAMS`-ba kerülnek, hogy a bíró paraméter-stabilitási próbája rájuk is fusson."""
    parent = registry.load(parent_id)
    p = {"parent": parent_id, "labels": list(labels), **(params or parent.meta.params)}
    return _header(parent.meta.family, hypothesis_id, parent_id, hypothesis, list(labels), falsifier) + f'''
from evolab.strategy import lib

TIMEFRAME = "{parent.meta.timeframe}"
PARAMS = {p!r}


def signals(bars, regime, params):
    base = {{k: v for k, v in params.items() if k not in ("parent", "labels")}}
    sig = lib.parent_signals(params["parent"], bars, regime, base)
    return lib.condition(sig, lib.regime_mask(regime, params["labels"]), "regime")
'''


def crossover(entry_id: str, exit_id: str, hypothesis_id: str, hypothesis: str, regimes: list[str],
              falsifier: str) -> str:
    """`crossover`: belépés az egyik, kilépési stop a másik variánsból (azonos idősík kell)."""
    a, b = registry.load(entry_id), registry.load(exit_id)
    if a.meta.timeframe != b.meta.timeframe:
        raise ValueError("a keresztezett variánsok idősíkja eltér")
    p = {"entry": entry_id, "exit": exit_id}
    return _header(a.meta.family, hypothesis_id, entry_id, hypothesis, regimes, falsifier) + f'''
from evolab.strategy import lib

TIMEFRAME = "{a.meta.timeframe}"
PARAMS = {p!r}


def signals(bars, regime, params):
    entry = lib.parent_signals(params["entry"], bars, regime)
    exit_ = lib.parent_signals(params["exit"], bars, regime)
    return lib.crossover(entry, exit_)
'''

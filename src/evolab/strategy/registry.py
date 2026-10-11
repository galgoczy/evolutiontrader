"""Stratégiafájlok felderítése és betöltése (`strategy/families/<család>/<variáns>.py`).

Azonosító: `<család>-<fájlnév, _ helyett ->`, pl. `families/trend/ema_cross_4h_01.py` ->
`trend-ema-cross-4h-01`. A registry elutasítja a fájlt, ha a YAML fejléc hiányos, a
`hypothesis` 200 karakternél rövidebb, vagy a család nem egyezik a mappával.
"""

from __future__ import annotations

import ast
import importlib.util
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import yaml

from evolab.strategy.base import BarFrame, RegimeFrame, SignalFrame, StrategyMeta, validate_signals

FAMILIES_DIR = Path(__file__).resolve().parent / "families"
MIN_HYPOTHESIS_CHARS = 200
TIMEFRAMES = ("1h", "4h")


class StrategyRejected(ValueError):
    pass


@dataclass
class LoadedStrategy:
    """A `Strategy` protokoll megvalósítása egy betöltött fájlhoz."""

    meta: StrategyMeta
    _fn: Any
    path: Path

    def signals(self, bars: BarFrame, regime: RegimeFrame) -> SignalFrame:
        return validate_signals(self._fn(bars, regime, dict(self.meta.params)), bars)

    def with_params(self, params: dict[str, Any]) -> "LoadedStrategy":
        """Ugyanaz a variáns más paraméterekkel (paraméter-stabilitás, rács)."""
        return LoadedStrategy(meta=replace(self.meta, params=dict(params)), _fn=self._fn, path=self.path)


def strategy_id(path: Path) -> str:
    return f"{path.parent.name}-{path.stem.replace('_', '-')}"


def parse_header(path: Path) -> dict[str, Any]:
    doc = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8")))
    if not doc:
        raise StrategyRejected(f"{path.name}: nincs YAML fejléc (modul-docstring)")
    try:
        header = yaml.safe_load(doc)
    except yaml.YAMLError as e:
        raise StrategyRejected(f"{path.name}: a fejléc nem érvényes YAML: {e}") from e
    if not isinstance(header, dict):
        raise StrategyRejected(f"{path.name}: a fejléc nem kulcs-érték YAML")
    return header


def check_header(header: dict[str, Any], family: str, name: str) -> None:
    if header.get("family") != family:
        raise StrategyRejected(f"{name}: a fejléc családja ({header.get('family')}) nem egyezik a mappával ({family})")
    hyp = str(header.get("hypothesis") or "").strip()
    if len(hyp) < MIN_HYPOTHESIS_CHARS:
        raise StrategyRejected(f"{name}: a hypothesis {len(hyp)} karakter, legalább {MIN_HYPOTHESIS_CHARS} kell")
    if not str(header.get("falsifier") or "").strip():
        raise StrategyRejected(f"{name}: hiányzik a falsifier")
    if not isinstance(header.get("expected_regimes"), list) or not header["expected_regimes"]:
        raise StrategyRejected(f"{name}: az expected_regimes nem üres lista kell legyen")


def load_file(path: Path) -> LoadedStrategy:
    path = Path(path)
    header = parse_header(path)
    check_header(header, path.parent.name, path.name)
    spec = importlib.util.spec_from_file_location(f"evolab_strategy_{strategy_id(path).replace('-', '_')}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for attr in ("TIMEFRAME", "PARAMS", "signals"):
        if not hasattr(module, attr):
            raise StrategyRejected(f"{path.name}: hiányzik a `{attr}`")
    if module.TIMEFRAME not in TIMEFRAMES:
        raise StrategyRejected(f"{path.name}: TIMEFRAME csak {TIMEFRAMES} lehet")
    meta = StrategyMeta(
        id=strategy_id(path), family=header["family"], timeframe=module.TIMEFRAME,
        params=dict(module.PARAMS), parent_id=header.get("parent_id"),
        hypothesis_id=header.get("hypothesis_id"), header=header,
    )
    return LoadedStrategy(meta=meta, _fn=module.signals, path=path)


def discover(root: Path = FAMILIES_DIR) -> dict[str, Path]:
    """Minden variánsfájl: azonosító -> útvonal."""
    files = sorted(p for p in root.glob("*/*.py") if not p.name.startswith("_"))
    return {strategy_id(p): p for p in files}


def load(strategy: str, root: Path = FAMILIES_DIR) -> LoadedStrategy:
    files = discover(root)
    if strategy not in files:
        known = ", ".join(files) or "nincs"
        raise KeyError(f"Ismeretlen stratégia: {strategy}. Ismert: {known}")
    return load_file(files[strategy])

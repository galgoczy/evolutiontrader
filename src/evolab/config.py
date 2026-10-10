"""Konfiguráció betöltése a config/ mappából és a .env fájlból."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


def find_root(start: Path | None = None) -> Path:
    """A repó gyökere: az első szülőmappa, amiben van config/lab.yaml."""
    env_root = os.environ.get("EVOLAB_ROOT")
    if env_root:
        return Path(env_root).resolve()
    here = (start or Path.cwd()).resolve()
    for p in (here, *here.parents):
        if (p / "config" / "lab.yaml").is_file():
            return p
    # telepített csomagból: src/evolab/config.py -> repó gyökér
    pkg_root = Path(__file__).resolve().parents[2]
    if (pkg_root / "config" / "lab.yaml").is_file():
        return pkg_root
    raise FileNotFoundError("Nem találom a config/lab.yaml fájlt. A repó gyökeréből futtasd.")


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@dataclass(frozen=True)
class Config:
    root: Path
    lab: dict[str, Any]
    judge: dict[str, Any]
    families: dict[str, Any]

    def path(self, key: str) -> Path:
        """Abszolút útvonal a lab.yaml `paths` blokkjából."""
        return self.root / self.lab["paths"][key]

    @property
    def db_path(self) -> Path:
        return self.path("db")

    @property
    def stop_file(self) -> Path:
        return self.root / "STOP"

    @property
    def judge_version(self) -> int:
        return int(self.judge["version"])


@lru_cache(maxsize=1)
def load_config(root: Path | None = None) -> Config:
    root = root or find_root()
    load_dotenv(root / ".env", override=False)
    return Config(
        root=root,
        lab=_load_yaml(root / "config" / "lab.yaml"),
        judge=_load_yaml(root / "config" / "judge.yaml"),
        families=_load_yaml(root / "config" / "families.yaml"),
    )

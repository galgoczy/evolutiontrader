import shutil
from pathlib import Path

import pytest

from evolab.config import load_config

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    """Ideiglenes repó-másolat (config + db séma), hogy a teszt ne nyúljon a valódi data/-hoz."""
    shutil.copytree(REPO / "config", tmp_path / "config")
    shutil.copytree(REPO / "db", tmp_path / "db")
    monkeypatch.setenv("EVOLAB_ROOT", str(tmp_path))
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    load_config.cache_clear()
    yield load_config(tmp_path)
    load_config.cache_clear()

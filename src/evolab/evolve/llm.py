"""LLM-hívás a helyi Claude Code CLI-n át (`claude -p`), a felhasználó előfizetésével.

Felhasználói döntés (2026-10-12): a kutató és a fejlesztő is a CLI-t használja, nem az Anthropic
API-t. A modell azonosítója a `config/lab.yaml`-ban van (`researcher.model`, `developer.model`).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class LLMError(RuntimeError):
    pass


@dataclass
class LLMResult:
    output: object          # strukturált kimenet (dict) vagy a válasz szövege
    cost_usd: float | None
    turns: int | None
    raw: dict


def claude_bin() -> str:
    found = shutil.which("claude")
    if found:
        return found
    for cand in (Path.home() / ".npm-global/bin/claude", Path.home() / ".local/bin/claude",
                 Path("/opt/homebrew/bin/claude")):
        if cand.exists():
            return str(cand)
    raise LLMError("Nem találom a `claude` parancsot (Claude Code CLI). Telepítve és bejelentkezve van?")


def run_cli(prompt: str, model: str, cwd: Path | None = None, schema: dict | None = None,
            allowed_tools: list[str] | None = None, disallowed_tools: list[str] | None = None,
            permission_mode: str | None = None, timeout_s: int = 900) -> LLMResult:
    """Egy fej nélküli Claude Code futás. `schema` esetén a kimenet a séma szerinti dict."""
    cmd = [claude_bin(), "-p", prompt, "--model", model, "--output-format", "json", "--no-session-persistence"]
    if schema is not None:
        cmd += ["--json-schema", json.dumps(schema)]
    if allowed_tools:
        cmd += ["--allowedTools", *allowed_tools]
    if disallowed_tools:
        cmd += ["--disallowedTools", *disallowed_tools]
    if permission_mode:
        cmd += ["--permission-mode", permission_mode]
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout_s, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as e:
        raise LLMError(f"a Claude-futás {timeout_s} mp után sem ért véget") from e
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise LLMError(f"a Claude-kimenet nem JSON (kód {proc.returncode}): "
                       f"{(proc.stderr or proc.stdout)[:300]}") from e
    if data.get("is_error") or proc.returncode != 0:
        raise LLMError(f"Claude-hiba: {str(data.get('result') or proc.stderr)[:300]}")
    out = data.get("structured_output") if schema is not None else data.get("result")
    if schema is not None and out is None:
        raise LLMError("a Claude nem adott strukturált kimenetet")
    return LLMResult(out, data.get("total_cost_usd"), data.get("num_turns"), data)


def template_text(path: Path) -> str:
    """Promptsablon a fejléc-kommentek (<!-- -->) nélkül: azok a fejlesztőnek szólnak, nem az LLM-nek."""
    return re.sub(r"<!--.*?-->\s*", "", path.read_text(encoding="utf-8"), flags=re.S)

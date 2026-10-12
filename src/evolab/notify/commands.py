"""Telegram-parancsok (docs/02-specifikacio.md 6.4): jóváhagyás és állapot.

Csak a `.env` `TELEGRAM_CHAT_ID`-jéből érkező üzenetet fogadja el; minden mást figyelmen kívül hagy.
Parancsok:
  /approve <id>          egy szinttel feljebb (L1 -> L2 paper, L2 -> L3), ha a bíró szerint jogosult
  /reject <id> <ok>      várólistás (L1) stratégia elutasítása
  /waiting               a várólista
  /status                rövid állapot
  /help                  súgó
A feldolgozott üzenetek azonosítója (`data/telegram_offset.json`) miatt egy parancs egyszer fut le.
A launchd paper-feladata óránként lekérdezi (`evolab telegram-poll`).
"""

from __future__ import annotations

import json
import os

from evolab.config import Config
from evolab.evolve import ladder
from evolab.notify import telegram

HELP = ("Parancsok:\n/approve <id> – jóváhagyás (L1→L2 paper, L2→L3)\n/reject <id> <ok> – várólistás elutasítása\n"
        "/waiting – várólista\n/status – állapot\n/help – súgó")


def _offset_path(cfg: Config):
    return cfg.path("data") / "telegram_offset.json"


def handle(cfg: Config, text: str) -> str:
    """Egy parancs végrehajtása; a válasz szövege."""
    parts = text.strip().split()
    if not parts:
        return HELP
    cmd = parts[0].split("@")[0].lower()
    try:
        if cmd == "/approve" and len(parts) >= 2:
            return "✅ " + ladder.approve(cfg, parts[1])
        if cmd == "/reject" and len(parts) >= 2:
            return "🛑 " + ladder.reject(cfg, parts[1], " ".join(parts[2:]))
        if cmd == "/waiting":
            w = ladder.waiting(cfg)
            return "Várólista üres." if w.empty else "Várólista:\n" + "\n".join(
                f"- {r.strategy_id} ({r.family}), {r.since[:10]} óta" for r in w.itertuples())
        if cmd == "/status":
            from evolab.report import daily

            return daily.telegram_text(daily.build(cfg))
    except ladder.LadderError as e:
        return f"⚠️ {e}"
    return HELP


def poll(cfg: Config, send=None, fetch=None) -> list[tuple[str, str]]:
    """Az új üzenetek feldolgozása. `send`/`fetch` tesztben cserélhető. Visszaad: (parancs, válasz) párok."""
    send = send or telegram.send
    fetch = fetch or telegram.updates
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    path = _offset_path(cfg)
    offset = json.loads(path.read_text())["offset"] if path.exists() else None
    done = []
    last = None
    for upd in fetch(offset):
        last = upd["update_id"]
        msg = upd.get("message") or {}
        if str((msg.get("chat") or {}).get("id")) != chat or not (msg.get("text") or "").startswith("/"):
            continue
        reply = handle(cfg, msg["text"])
        send(reply)
        done.append((msg["text"], reply))
    if last is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"offset": last + 1}))
    return done

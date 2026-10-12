"""Telegram értesítés a Bot API-n át (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID a .env-ben)."""

from __future__ import annotations

import os

API = "https://api.telegram.org/bot{token}/{method}"


class TelegramNotConfigured(RuntimeError):
    pass


def _token() -> str:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise TelegramNotConfigured("Hiányzik a TELEGRAM_BOT_TOKEN a .env fájlból.")
    return token


def _call(method: str, **params) -> dict:
    import httpx  # lustán, hogy a CLI többi része nélküle is induljon

    resp = httpx.post(API.format(token=_token(), method=method), json=params, timeout=20)
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram hiba ({method}): {data.get('description', resp.text)}")
    return data["result"]


def send(text: str, chat_id: str | None = None) -> int:
    """Üzenet küldése. Visszaadja az üzenet azonosítóját."""
    _token()  # előbb a token hiányát jelezzük
    chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not chat_id:
        raise TelegramNotConfigured(
            "Hiányzik a TELEGRAM_CHAT_ID. Írj a botnak, majd futtasd: uv run evolab telegram-chatid"
        )
    result = _call("sendMessage", chat_id=chat_id, text=text, disable_web_page_preview=True)
    return int(result["message_id"])


def recent_chats() -> list[tuple[str, str]]:
    """A botnak írt legutóbbi üzenetek feladói: (chat_id, név)."""
    seen: dict[str, str] = {}
    for upd in _call("getUpdates", timeout=0):
        msg = upd.get("message") or upd.get("edited_message") or {}
        chat = msg.get("chat") or {}
        if "id" in chat:
            name = chat.get("username") or chat.get("first_name") or chat.get("title") or ""
            seen[str(chat["id"])] = name
    return list(seen.items())


def updates(offset: int | None = None) -> list[dict]:
    """Új üzenetek a bothoz (getUpdates, várakozás nélkül)."""
    params = {"timeout": 0}
    if offset is not None:
        params["offset"] = offset
    return _call("getUpdates", **params)

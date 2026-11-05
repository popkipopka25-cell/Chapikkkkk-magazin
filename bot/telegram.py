"""Минимальный клиент Telegram Bot API.

Без BOT_TOKEN работает тестовый режим: сообщения не отправляются, а складываются
в OUTBOX (видно в логах и тестах). Отправка нигде не имитируется как реальная.
"""
import logging

import httpx

from app.config import get_settings

log = logging.getLogger("chapashop.bot")
OUTBOX: list[dict] = []
API = "https://api.telegram.org/bot{token}/{method}"


class TelegramError(Exception):
    pass


def call(method: str, **params) -> dict | None:
    params = {k: v for k, v in params.items() if v is not None}
    token = get_settings().bot_token
    if not token:
        OUTBOX.append({"method": method, **params})
        log.info("[ТЕСТОВЫЙ РЕЖИМ] %s не отправлен: BOT_TOKEN не задан", method)
        return None
    try:
        r = httpx.post(API.format(token=token, method=method), json=params, timeout=10)
        data = r.json()
    except Exception as e:  # сеть, таймаут
        log.error("Telegram %s: ошибка сети %s", method, e.__class__.__name__)
        raise TelegramError("network") from e
    if not data.get("ok"):
        log.error("Telegram %s: %s", method, data.get("description"))
        raise TelegramError(data.get("description", "error"))
    return data.get("result")


def send_message(chat_id: int, text: str, reply_markup: dict | None = None) -> bool:
    """Отправка сообщения. Возвращает False при ошибке (например, пользователь заблокировал бота)."""
    try:
        call("sendMessage", chat_id=chat_id, text=text, parse_mode="HTML",
             reply_markup=reply_markup, disable_web_page_preview=True)
        return True
    except TelegramError:
        return False


def send_document(chat_id: int, filename: str, content: bytes, caption: str | None = None) -> bool:
    """Отправка файла (например, PDF-чека). В тестовом режиме файл кладётся в OUTBOX."""
    token = get_settings().bot_token
    if not token:
        OUTBOX.append({"method": "sendDocument", "chat_id": chat_id, "filename": filename,
                       "size": len(content), "caption": caption})
        log.info("[ТЕСТОВЫЙ РЕЖИМ] sendDocument не отправлен: BOT_TOKEN не задан")
        return False
    try:
        r = httpx.post(API.format(token=token, method="sendDocument"),
                       data={"chat_id": str(chat_id), "caption": caption or "", "parse_mode": "HTML"},
                       files={"document": (filename, content, "application/pdf")}, timeout=20)
        data = r.json()
    except Exception as e:
        log.error("Telegram sendDocument: ошибка сети %s", e.__class__.__name__)
        return False
    if not data.get("ok"):
        log.error("Telegram sendDocument: %s", data.get("description"))
        return False
    return True

"""Проверка Telegram Mini App initData (официальный алгоритм HMAC-SHA256)."""
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

MAX_AGE = 24 * 3600


class InitDataError(ValueError):
    pass


def verify_init_data(init_data: str, bot_token: str, max_age: int = MAX_AGE) -> dict:
    """Возвращает данные пользователя Telegram только если подпись верна и данные свежие."""
    if not bot_token:
        raise InitDataError("bot token not configured")
    if not init_data or len(init_data) > 4096:
        raise InitDataError("empty")
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received = pairs.pop("hash", None)
    if not received:
        raise InitDataError("no hash")
    check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, received):
        raise InitDataError("bad signature")
    try:
        auth_date = int(pairs.get("auth_date", "0"))
    except ValueError:
        raise InitDataError("bad auth_date")
    if max_age and time.time() - auth_date > max_age:
        raise InitDataError("expired")
    try:
        user = json.loads(pairs.get("user", ""))
    except Exception:
        raise InitDataError("no user")
    if not isinstance(user, dict) or not isinstance(user.get("id"), int):
        raise InitDataError("no user")
    return user


def sign_init_data(fields: dict, bot_token: str) -> str:
    """Для тестов: формирует корректно подписанную строку initData."""
    from urllib.parse import urlencode
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    h = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode({**fields, "hash": h})

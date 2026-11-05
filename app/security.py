"""Пароли владельца и сессии панели. Только стандартная библиотека Python."""
import base64
import hashlib
import hmac
import secrets
import time

from app.config import get_settings

ITER = 260_000
SESSION_TTL = 12 * 3600
COOKIE = "cs_admin"


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITER)
    return f"pbkdf2${ITER}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, it, salt, dk = stored.split("$")
        if algo != "pbkdf2":
            return False
        calc = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt), int(it))
        return hmac.compare_digest(calc, base64.b64decode(dk))
    except Exception:
        return False


def _sign(msg: str, pw_hash: str) -> str:
    # В подпись входит хеш пароля: смена пароля завершает все старые сессии.
    key = (get_settings().secret_key + pw_hash).encode()
    return hmac.new(key, msg.encode(), hashlib.sha256).hexdigest()


def make_session(admin_id: int, pw_hash: str) -> tuple[str, str]:
    """Возвращает (cookie, csrf). CSRF-токен привязан к сессии."""
    exp = int(time.time()) + SESSION_TTL
    msg = f"{admin_id}.{exp}"
    token = f"{msg}.{_sign(msg, pw_hash)}"
    return token, csrf_for(token)


def parse_session(token: str | None) -> tuple[int, int] | None:
    """Возвращает (admin_id, exp) без проверки подписи — подпись проверяет read_session."""
    try:
        aid, exp, _ = (token or "").split(".")
        return int(aid), int(exp)
    except ValueError:
        return None


def check_session(token: str, pw_hash: str) -> bool:
    parsed = parse_session(token)
    if not parsed or parsed[1] < time.time():
        return False
    msg, sig = token.rsplit(".", 1)
    return hmac.compare_digest(sig, _sign(msg, pw_hash))


def csrf_for(token: str) -> str:
    return hmac.new(get_settings().secret_key.encode(), b"csrf:" + token.encode(), hashlib.sha256).hexdigest()

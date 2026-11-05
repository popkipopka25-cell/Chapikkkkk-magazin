"""Промокоды: проверка и расчёт скидки. Скидка всегда считается на сервере."""
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Order, OrderStatus, PromoCode

CODE_RE = re.compile(r"^[A-Z0-9_-]{3,32}$")


def normalize(code: str | None) -> str:
    return (code or "").strip().upper()[:32]


def discount_for(promo: PromoCode, subtotal: int) -> int:
    """Скидка в Stars. Итог к оплате никогда не меньше 1 ⭐ (минимум Telegram)."""
    if promo.percent:
        d = subtotal * promo.percent // 100
    else:
        d = promo.fixed_stars or 0
    return max(0, min(d, subtotal - 1))


def find_valid(db: Session, code: str | None, user_id: int | None = None) -> tuple[PromoCode | None, str | None]:
    """Возвращает (промокод, None) или (None, текст ошибки)."""
    code = normalize(code)
    if not code:
        return None, None
    promo = db.scalar(select(PromoCode).where(PromoCode.code == code))
    if promo is None or not promo.is_active:
        return None, "Промокод не найден"
    if promo.max_uses is not None and promo.used_count >= promo.max_uses:
        return None, "Лимит использований промокода исчерпан"
    if user_id is not None:
        used = db.scalar(select(Order.id).where(
            Order.user_id == user_id, Order.promo_code == promo.code,
            Order.status != OrderStatus.rejected).limit(1))
        if used:
            return None, "Вы уже использовали этот промокод"
    return promo, None

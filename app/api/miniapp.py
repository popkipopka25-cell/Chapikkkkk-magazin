"""API Telegram Mini App: авторизация, профиль, заказы. Telegram ID берётся только из проверенного initData."""
import hashlib
import hmac
import re
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import Response as RawResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app import promo as promo_mod
from app import stock as stock_mod
from app.models import (ORDER_STATUS_RU, Order, OrderItem, OrderStatus, OrderStatusHistory, Payment, PaymentStatus,
                        Product, PromoCode, Setting, User)
from app.tg_auth import InitDataError, verify_init_data

router = APIRouter(prefix="/api", tags=["miniapp"])
ROBLOX_RE = re.compile(r"^[A-Za-z0-9_]{3,20}$")
MAX_QTY, MAX_LINES = 99, 50

# Простое ограничение частоты создания заказов: 5 в минуту на пользователя.
_hits: dict[int, deque] = defaultdict(deque)


def _rate_limit(tg_id: int, limit: int = 5, window: int = 60):
    q, t = _hits[tg_id], time.monotonic()
    while q and t - q[0] > window:
        q.popleft()
    if len(q) >= limit:
        raise HTTPException(429, "Слишком много заказов, подождите минуту")
    q.append(t)


FREE_LIMIT, FREE_WINDOW_HOURS = 3, 24


def _free_limit(db: Session, user: User) -> None:
    """Защита от накрутки: не больше 3 бесплатных заказов в сутки на человека."""
    since = datetime.now(timezone.utc) - timedelta(hours=FREE_WINDOW_HOURS)
    n = db.scalar(select(func.count()).select_from(Order).where(
        Order.user_id == user.id, Order.total_stars == 0, Order.created_at > since,
        Order.status != OrderStatus.rejected)) or 0
    if n >= FREE_LIMIT:
        raise HTTPException(429, "Бесплатные товары: не больше 3 заказов в сутки")


def current_user(db: Session = Depends(get_db),
                 x_telegram_init_data: str = Header(default="")) -> User:
    try:
        tg = verify_init_data(x_telegram_init_data, get_settings().bot_token)
    except InitDataError:
        raise HTTPException(401, "Откройте магазин через Telegram")
    user = db.scalar(select(User).where(User.telegram_id == tg["id"]))
    if user is None:
        user = User(telegram_id=tg["id"])
        db.add(user)
    user.username = (tg.get("username") or None)
    user.first_name = (str(tg.get("first_name") or "")[:128]) or None
    db.commit()
    return user


def _vip_link(db: Session) -> str | None:
    """Общая ссылка на VIP-сервер из настроек панели (пусто — не задана)."""
    s = db.get(Setting, "vip_server_link")
    return ((s.value if s else "") or "").strip() or None


# Покупатель видит ссылку на сервер только после оплаты.
LINK_STATUSES = ("paid", "processing", "awaiting_delivery", "delivered")


def _order_out(o: Order, vip: str | None = None) -> dict:
    link = o.server_link or (vip if o.status.value in LINK_STATUSES else None)
    return {
        "id": o.id, "number": o.number, "created_at": o.created_at.isoformat(),
        "roblox_username": o.roblox_username, "total_stars": o.total_stars,
        "promo_code": o.promo_code, "discount_stars": o.discount_stars or 0,
        "payment_status": o.payment_status.value, "status": o.status.value,
        "status_ru": ORDER_STATUS_RU[o.status.value], "server_link": link,
        "items": [{"name": i.product_name, "price_stars": i.price_stars, "quantity": i.quantity,
                   "subtotal": i.price_stars * i.quantity} for i in o.items],
        "history": [{"status": h.new_status, "status_ru": ORDER_STATUS_RU.get(h.new_status, h.new_status),
                     "comment": h.comment if h.new_status == "rejected" else None,
                     "at": h.created_at.isoformat()} for h in sorted(o.history, key=lambda x: x.id)],
        "has_receipt": o.payment_status.value in ("paid", "refunded"),
    }


@router.get("/me")
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    count = len(db.scalars(select(Order.id).where(Order.user_id == user.id)).all())
    return {"telegram_id": user.telegram_id, "username": user.username, "first_name": user.first_name,
            "roblox_username": user.roblox_username, "orders_count": count,
            "is_blocked": bool(user.is_blocked)}


class RobloxIn(BaseModel):
    roblox_username: str = Field(max_length=20)


@router.put("/me/roblox")
def set_roblox(body: RobloxIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    nick = body.roblox_username.strip()
    if not ROBLOX_RE.match(nick):
        raise HTTPException(422, "3–20 символов: латиница, цифры и _")
    user.roblox_username = nick
    db.commit()
    return {"roblox_username": nick}


@router.get("/orders")
def my_orders(user: User = Depends(current_user), db: Session = Depends(get_db)):
    orders = db.scalars(select(Order).where(Order.user_id == user.id).order_by(Order.id.desc()).limit(100)).all()
    vip = _vip_link(db)
    return [_order_out(o, vip) for o in orders]


@router.get("/orders/{order_id}")
def my_order(order_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    o = db.get(Order, order_id)
    if o is None or o.user_id != user.id:   # чужие заказы не видны
        raise HTTPException(404, "Заказ не найден")
    return _order_out(o, _vip_link(db))


class LineIn(BaseModel):
    product_id: int
    quantity: int = Field(ge=1, le=MAX_QTY)


class OrderIn(BaseModel):
    items: list[LineIn] = Field(min_length=1, max_length=MAX_LINES)
    roblox_username: str = Field(max_length=20)
    promo_code: str | None = Field(None, max_length=32)


def ensure_not_blocked(user: User) -> None:
    if user.is_blocked:
        raise HTTPException(403, "Ваш аккаунт заблокирован. Обратитесь в поддержку.")


@router.post("/orders", status_code=201)
def create_order(body: OrderIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ensure_not_blocked(user)
    nick = body.roblox_username.strip()
    if not ROBLOX_RE.match(nick):
        raise HTTPException(422, "Неверный Roblox username")
    _rate_limit(user.telegram_id)
    merged: dict[int, int] = {}
    for l in body.items:
        merged[l.product_id] = min(MAX_QTY, merged.get(l.product_id, 0) + l.quantity)
    products = {p.id: p for p in db.scalars(select(Product).where(Product.id.in_(merged))).all()}
    items, total = [], 0
    for pid, qty in merged.items():
        p = products.get(pid)
        if p is None or p.is_hidden or not p.available_now:
            raise HTTPException(409, f"Товар {pid} недоступен — обновите корзину")
        items.append(OrderItem(product_id=p.id, product_name=p.name, price_stars=p.price_stars, quantity=qty))
        total += p.price_stars * qty
    discount, promo_text = 0, None
    if total == 0:
        _free_limit(db, user)
    if body.promo_code and body.promo_code.strip():
        if total == 0:
            raise HTTPException(409, "Товар бесплатный — промокод не нужен")
        promo, err = promo_mod.find_valid(db, body.promo_code, user.id)
        if promo is None:
            raise HTTPException(409, err or "Промокод не найден")
        discount, promo_text = promo_mod.discount_for(promo, total), promo.code
        # Атомарно занимаем одно использование: два одновременных заказа не обойдут лимит.
        got = db.execute(update(PromoCode).where(
            PromoCode.id == promo.id, PromoCode.is_active.is_(True),
            or_(PromoCode.max_uses.is_(None), PromoCode.used_count < PromoCode.max_uses)
        ).values(used_count=PromoCode.used_count + 1))
        if got.rowcount != 1:
            db.rollback()
            raise HTTPException(409, "Лимит использований промокода исчерпан")
    # Остаток на складе: забираем штуки атомарно, чтобы два покупателя не купили последний товар одновременно.
    for pid, qty in merged.items():
        p = products[pid]
        name = p.name
        if not stock_mod.take(db, p, qty):
            db.rollback()
            left = db.scalar(select(Product.stock).where(Product.id == pid)) or 0
            raise HTTPException(409, f"Товара «{name}» осталось {left} шт. — уменьшите количество" if left
                                else f"Товар «{name}» закончился")
    free = total - discount <= 0           # бесплатный заказ: платить нечего, сразу «Оплачен» и ждёт выдачи
    first = OrderStatus.paid if free else OrderStatus.awaiting_payment
    o = Order(user_id=user.id, telegram_id=user.telegram_id, roblox_username=nick, total_stars=total - discount,
              promo_code=promo_text, discount_stars=discount,
              payment_status=PaymentStatus.paid if free else PaymentStatus.pending, status=first,
              items=items, history=[OrderStatusHistory(old_status=None, new_status=first.value, changed_by="customer",
                                                        comment="Бесплатный товар" if free else None)])
    user.roblox_username = nick
    db.add(o)
    db.commit()   # номер заказа = автоинкремент БД, конфликтов при одновременном создании нет
    db.refresh(o)
    from bot import notify
    try:
        (notify.order_paid if free else notify.order_created)(db, o)    # бесплатный заказ: кнопки «Оплатить» нет
    except Exception:
        pass
    return _order_out(o, _vip_link(db))


@router.post("/orders/{order_id}/invoice")
def order_invoice(order_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Создаёт настоящий invoice Telegram Stars. Оплата засчитывается только по successful_payment."""
    from bot import payments
    from bot.telegram import TelegramError
    ensure_not_blocked(user)
    o = db.get(Order, order_id)
    if o is None or o.user_id != user.id:
        raise HTTPException(404, "Заказ не найден")
    if not payments.can_pay(o):
        raise HTTPException(409, "Заказ уже оплачен или отменён")
    try:
        link = payments.create_invoice_link(o)
    except TelegramError:
        raise HTTPException(502, "Telegram не создал счёт, попробуйте позже")
    if not link:
        raise HTTPException(503, "Тестовый режим: оплата не подключена")
    return {"invoice_link": link}


_receipt_hits: dict[int, deque] = defaultdict(deque)


@router.post("/orders/{order_id}/receipt")
def send_my_receipt(order_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Покупатель просит прислать PDF-чек в чат с ботом (не чаще 3 раз в минуту)."""
    o = db.get(Order, order_id)
    if o is None or o.user_id != user.id:
        raise HTTPException(404, "Заказ не найден")
    if o.payment_status.value not in ("paid", "refunded"):
        raise HTTPException(400, "Чек появится после оплаты")
    q, t = _receipt_hits[user.id], time.monotonic()
    while q and t - q[0] > 60:
        q.popleft()
    if len(q) >= 3:
        raise HTTPException(429, "Подождите минуту")
    q.append(t)
    from bot import notify
    return {"ok": True, "sent": notify.receipt(db, o)}


# ---------- Скачивание PDF-чека покупателем ----------
# В Telegram нельзя скачать файл из запроса с заголовком авторизации, поэтому выдаём короткую
# подписанную ссылку: она живёт 10 минут и открывает только чек одного заказа.
RECEIPT_TTL = 600
public_router = APIRouter(tags=["receipt"])


def _receipt_sig(order_id: int, exp: int) -> str:
    key = get_settings().secret_key.encode()
    return hmac.new(key, f"receipt:{order_id}:{exp}".encode(), hashlib.sha256).hexdigest()[:32]


@router.post("/orders/{order_id}/receipt-link")
def my_receipt_link(order_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    o = db.get(Order, order_id)
    if o is None or o.user_id != user.id:
        raise HTTPException(404, "Заказ не найден")
    if o.payment_status.value not in ("paid", "refunded"):
        raise HTTPException(400, "Чек появится после оплаты")
    q, t = _receipt_hits[user.id], time.monotonic()
    while q and t - q[0] > 60:
        q.popleft()
    if len(q) >= 10:
        raise HTTPException(429, "Подождите минуту")
    q.append(t)
    exp = int(time.time()) + RECEIPT_TTL
    return {"url": f"/receipt/{o.id}/{exp}/{_receipt_sig(o.id, exp)}.pdf"}


@public_router.get("/receipt/{order_id}/{exp}/{sig}.pdf", include_in_schema=False)
def receipt_by_link(order_id: int, exp: int, sig: str, db: Session = Depends(get_db)):
    if exp < time.time() or not hmac.compare_digest(sig, _receipt_sig(order_id, exp)):
        raise HTTPException(403, "Ссылка устарела. Откройте заказ и нажмите «Скачать PDF» ещё раз.")
    o = db.get(Order, order_id)
    if o is None or o.payment_status.value not in ("paid", "refunded"):
        raise HTTPException(404, "Чек не найден")
    from app.receipt import build_receipt
    pay = db.scalar(select(Payment).where(Payment.order_id == o.id).order_by(Payment.id))
    shop = db.get(Setting, "shop_name")
    pdf = build_receipt(o, pay, shop.value if shop and shop.value else "ChapaShop")
    return RawResponse(pdf, media_type="application/pdf",
                       headers={"Content-Disposition": f'attachment; filename="ChapaShop_chek_{o.number}.pdf"',
                                "Cache-Control": "no-store"})

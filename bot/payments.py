"""Оплата Telegram Stars (XTR).

Порядок по правилам Telegram:
1. Создаём invoice (createInvoiceLink / sendInvoice) с currency=XTR и provider_token="".
2. На pre_checkout_query проверяем заказ и сумму и отвечаем answerPreCheckoutQuery за 10 секунд.
3. Заказ становится «Оплачен» ТОЛЬКО после message.successful_payment.
4. telegram_payment_charge_id уникален в БД — повторное зачисление невозможно.
"""
import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Order, OrderStatus, OrderStatusHistory, Payment, PaymentStatus, User
from bot.telegram import TelegramError, call

log = logging.getLogger("chapashop.pay")
PAYLOAD_PREFIX = "order:"


def _payload(o: Order) -> str:
    return f"{PAYLOAD_PREFIX}{o.id}"


def _order_from_payload(db: Session, payload: str) -> Order | None:
    if not isinstance(payload, str) or not payload.startswith(PAYLOAD_PREFIX):
        return None
    try:
        return db.get(Order, int(payload[len(PAYLOAD_PREFIX):]))
    except ValueError:
        return None


def _invoice_params(o: Order) -> dict:
    names = ", ".join(f"{i.product_name} ×{i.quantity}" for i in o.items)[:255] or "Заказ"
    return {"title": f"ChapaShop — заказ {o.number}"[:32], "description": names,
            "payload": _payload(o), "provider_token": "", "currency": "XTR",
            "prices": [{"label": f"Заказ {o.number}", "amount": o.total_stars}]}


def can_pay(o: Order) -> bool:
    return o.payment_status == PaymentStatus.pending and o.status == OrderStatus.awaiting_payment


def create_invoice_link(o: Order) -> str | None:
    """Ссылка для Telegram.WebApp.openInvoice. None — тестовый режим (нет BOT_TOKEN)."""
    return call("createInvoiceLink", **_invoice_params(o))


def send_invoice(o: Order) -> bool:
    try:
        call("sendInvoice", chat_id=o.telegram_id, **_invoice_params(o))
        return True
    except TelegramError:
        return False


def check_pre_checkout(db: Session, q: dict) -> tuple[bool, str | None]:
    o = _order_from_payload(db, q.get("invoice_payload"))
    if o is None:
        return False, "Заказ не найден"
    if o.telegram_id != q.get("from", {}).get("id"):
        return False, "Это не ваш заказ"
    if not can_pay(o):
        return False, "Заказ уже оплачен или отменён"
    buyer = db.get(User, o.user_id)
    if buyer is not None and buyer.is_blocked:
        return False, "Аккаунт заблокирован"
    if q.get("currency") != "XTR" or q.get("total_amount") != o.total_stars:
        return False, "Сумма заказа изменилась, оформите заказ заново"
    return True, None


def handle_pre_checkout(db: Session, q: dict) -> bool:
    ok, err = check_pre_checkout(db, q)
    try:
        call("answerPreCheckoutQuery", pre_checkout_query_id=q["id"], ok=ok, error_message=err)
    except TelegramError:
        log.error("answerPreCheckoutQuery не отправлен")
    return ok


def handle_successful_payment(db: Session, msg: dict) -> str:
    """Возвращает: paid | duplicate | review."""
    sp = msg["successful_payment"]
    charge = sp.get("telegram_payment_charge_id")
    if not charge:
        return "review"
    if db.scalar(select(Payment).where(Payment.telegram_payment_charge_id == charge)):
        return "duplicate"
    o = _order_from_payload(db, sp.get("invoice_payload"))
    amount = int(sp.get("total_amount") or 0)
    valid = (o is not None and can_pay(o) and sp.get("currency") == "XTR"
             and amount == o.total_stars and o.telegram_id == msg.get("from", {}).get("id"))
    if o is None:
        log.error("Платёж %s без заказа — нужна проверка владельцем", charge[:6])
        return "review"
    pay = Payment(order_id=o.id, telegram_payment_charge_id=charge, amount_stars=amount,
                  currency=sp.get("currency", "XTR"), status="succeeded" if valid else "needs_review",
                  raw={k: sp.get(k) for k in ("currency", "total_amount", "invoice_payload",
                                               "telegram_payment_charge_id", "provider_payment_charge_id")})
    db.add(pay)
    if valid:
        o.history.append(OrderStatusHistory(old_status=o.status.value, new_status=OrderStatus.paid.value,
                                            changed_by="telegram", comment=f"Stars: {amount}"))
        o.payment_status = PaymentStatus.paid
        o.status = OrderStatus.paid
    try:
        db.commit()
    except IntegrityError:   # одновременный повтор того же платежа
        db.rollback()
        return "duplicate"
    if valid:
        from bot import notify
        notify.order_paid(db, o)
        return "paid"
    log.error("Платёж по заказу %s не совпал с заказом — нужна проверка", o.number)
    return "review"


def refund(db: Session, o: Order, actor: str = "owner") -> bool:
    """Возврат Stars через refundStarPayment (используется панелью владельца)."""
    pay = db.scalar(select(Payment).where(Payment.order_id == o.id, Payment.status == "succeeded"))
    if pay is None:
        return False
    call("refundStarPayment", user_id=o.telegram_id, telegram_payment_charge_id=pay.telegram_payment_charge_id)
    pay.status = "refunded"
    o.history.append(OrderStatusHistory(old_status=o.status.value, new_status=OrderStatus.refunded.value, changed_by=actor))
    o.payment_status = PaymentStatus.refunded
    o.status = OrderStatus.refunded
    db.commit()
    return True

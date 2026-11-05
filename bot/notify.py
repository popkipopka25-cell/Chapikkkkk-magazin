"""Уведомления покупателю. Вызываются из заказов, оплаты и панели владельца (этапы 5–7)."""
from sqlalchemy.orm import Session

from app.models import ORDER_STATUS_RU, Order
from bot import keyboards
from bot.telegram import send_message
from bot.texts import get_text


def _fmt(o: Order) -> dict:
    return {"number": o.number, "total": o.total_stars, "roblox": o.roblox_username,
            "status": ORDER_STATUS_RU[o.status.value if hasattr(o.status, "value") else o.status]}


def order_created(db: Session, o: Order) -> bool:
    kb = keyboards.order_buttons()
    pay_row = [{"text": f"Оплатить {o.total_stars} ⭐", "callback_data": f"pay:{o.id}"}]
    kb = {"inline_keyboard": [pay_row] + list((kb or {}).get("inline_keyboard", []))}
    return send_message(o.telegram_id, get_text(db, "notify_order_created", **_fmt(o)), kb)


def order_paid(db: Session, o: Order) -> bool:
    return send_message(o.telegram_id, get_text(db, "notify_paid", **_fmt(o)), keyboards.order_buttons())


def status_changed(db: Session, o: Order) -> bool:
    return send_message(o.telegram_id, get_text(db, "notify_status", **_fmt(o)), keyboards.order_buttons())


def server_link(db: Session, o: Order) -> bool:
    if not o.server_link:
        return False
    return send_message(o.telegram_id, get_text(db, "notify_server_link", **_fmt(o)), keyboards.order_buttons(o.server_link))


def delivered(db: Session, o: Order) -> bool:
    return send_message(o.telegram_id, get_text(db, "notify_delivered", **_fmt(o)), keyboards.order_buttons())


def rejected(db: Session, o: Order, reason: str | None = None) -> bool:
    from html import escape
    r = f"\nПричина: {escape(reason)}" if reason else ""
    return send_message(o.telegram_id, get_text(db, "notify_rejected", reason=r, **_fmt(o)), keyboards.order_buttons())


def receipt(db: Session, o: Order) -> bool:
    """PDF-чек в чат покупателя. Только для заказов с подтверждённой оплатой."""
    from sqlalchemy import select
    from app.models import Payment, Setting
    from app.receipt import build_receipt, can_have_receipt
    from bot.telegram import send_document
    if not can_have_receipt(o):
        return False
    pay = db.scalar(select(Payment).where(Payment.order_id == o.id).order_by(Payment.id))
    shop = db.get(Setting, "shop_name")
    pdf = build_receipt(o, pay, shop.value if shop and shop.value else "ChapaShop")
    return send_document(o.telegram_id, f"ChapaShop_chek_{o.number}.pdf", pdf,
                         get_text(db, "notify_receipt", **_fmt(o)))

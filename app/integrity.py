"""Проверка целостности данных (Этап 8). Только чтение — ничего не исправляет само."""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Order, OrderItem, OrderStatus, Payment, PaymentStatus

PAID_STATES = {OrderStatus.paid, OrderStatus.processing, OrderStatus.awaiting_delivery, OrderStatus.delivered}


def check(db: Session) -> dict:
    problems: list[dict] = []

    sums = dict(db.execute(select(OrderItem.order_id, func.sum(OrderItem.price_stars * OrderItem.quantity))
                           .group_by(OrderItem.order_id)).all())
    paid = {oid: amt for oid, amt in db.execute(
        select(Payment.order_id, func.sum(Payment.amount_stars))
        .where(Payment.status == "succeeded").group_by(Payment.order_id)).all()}

    for o in db.scalars(select(Order)):
        items_sum = sums.get(o.id)
        if items_sum is None:
            problems.append({"order": o.id, "issue": "Заказ без товаров"})
        elif items_sum - (o.discount_stars or 0) != o.total_stars:
            problems.append({"order": o.id, "issue": f"Сумма товаров {items_sum} − скидка {o.discount_stars or 0} ≠ итог {o.total_stars}"})
        if o.status in PAID_STATES and o.id not in paid:
            problems.append({"order": o.id, "issue": "Отмечен оплаченным, но платежа нет"})
        if o.id in paid and paid[o.id] != o.total_stars and o.status != OrderStatus.refunded:
            problems.append({"order": o.id, "issue": f"Оплачено {paid[o.id]} ≠ итог {o.total_stars}"})
        if o.status == OrderStatus.awaiting_payment and o.payment_status == PaymentStatus.paid:
            problems.append({"order": o.id, "issue": "Статус «Ожидает оплаты», но оплата отмечена"})

    dup = db.execute(select(Payment.telegram_payment_charge_id).group_by(Payment.telegram_payment_charge_id)
                     .having(func.count() > 1)).scalars().all()
    for c in dup:
        problems.append({"order": None, "issue": f"Повторный платёж {c}"})

    review = db.scalar(select(func.count()).select_from(Payment).where(Payment.status == "needs_review")) or 0
    return {"ok": not problems, "problems": problems, "payments_need_review": review,
            "orders_checked": db.scalar(select(func.count()).select_from(Order)) or 0}

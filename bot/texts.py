"""Тексты бота. Значения по умолчанию; владелец может менять их в настройках (таблица settings)."""
from html import escape

from sqlalchemy.orm import Session

from app.models import Setting

DEFAULTS = {
    "bot_welcome": "Привет, {name}! 👋\n\nПриветствуем вас в нашем шопе <b>ChapaShop</b> — товары Adopt Me с оплатой в Telegram Stars ⭐\n\nПо любому вопросу о шопе пишите: @ChapikSupport\n\nНажмите кнопку ниже, чтобы открыть магазин.",
    "bot_help": "<b>Команды</b>\n/shop — открыть магазин\n/profile — ваш профиль\n/orders — мои заказы\n/roblox <i>ник</i> — указать Roblox username\n/help — помощь\n\nПо любому вопросу о шопе пишите: @ChapikSupport",
    "bot_open_button": "🛍 Открыть ChapaShop",
    "notify_order_created": "🧾 Заказ <b>{number}</b> создан.\nСумма: <b>{total} ⭐</b>\nRoblox: <code>{roblox}</code>\n\nСтатус: {status}",
    "notify_paid": "✅ Оплата заказа <b>{number}</b> получена ({total} ⭐). Скоро начнём выдачу.",
    "notify_status": "🔔 Заказ <b>{number}</b>: новый статус — <b>{status}</b>.",
    "notify_server_link": "🎮 Заказ <b>{number}</b> готов к выдаче!\nЗайдите на приватный сервер по кнопке ниже под ником <code>{roblox}</code>.",
    "notify_delivered": "🎉 Заказ <b>{number}</b> выдан. Спасибо за покупку в ChapaShop!",
    "notify_receipt": "🧾 Чек по заказу <b>{number}</b> ({total} ⭐).",
    "notify_rejected": "❌ Заказ <b>{number}</b> отклонён.{reason}",
}


def get_text(db: Session, key: str, **fmt) -> str:
    row = db.get(Setting, key)
    tpl = row.value if row and row.value else DEFAULTS[key]
    safe = {k: escape(str(v)) if k != "reason" else v for k, v in fmt.items()}
    try:
        return tpl.format(**safe)
    except (KeyError, IndexError, ValueError):
        # Владелец ошибся в шаблоне — используем стандартный текст, чтобы бот не падал.
        return DEFAULTS[key].format(**safe)

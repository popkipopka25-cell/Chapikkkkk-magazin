"""Обработка входящих обновлений Telegram."""
import re
from html import escape

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ORDER_STATUS_RU, Order, User
from bot import keyboards
from bot.telegram import call, send_message, TelegramError
from bot.texts import get_text

ROBLOX_RE = re.compile(r"^[A-Za-z0-9_]{3,20}$")


def upsert_user(db: Session, tg: dict) -> User:
    user = db.scalar(select(User).where(User.telegram_id == tg["id"]))
    if user is None:
        user = User(telegram_id=tg["id"])
        db.add(user)
    user.username = (tg.get("username") or None)
    user.first_name = (tg.get("first_name") or "")[:128] or None
    db.commit()
    return user


def cmd_start(db, user, chat_id, _arg):
    text = get_text(db, "bot_welcome", name=user.first_name or "друг")
    send_message(chat_id, text, keyboards.main_menu(get_text(db, "bot_open_button")))


def cmd_shop(db, _user, chat_id, _arg):
    send_message(chat_id, "Магазин ChapaShop 👇", keyboards.main_menu(get_text(db, "bot_open_button")))


def cmd_help(db, _user, chat_id, _arg):
    send_message(chat_id, get_text(db, "bot_help"), keyboards.shop_only())


def cmd_profile(db, user, chat_id, _arg):
    count = db.scalar(select(func.count()).select_from(Order).where(Order.user_id == user.id)) or 0
    roblox = escape(user.roblox_username) if user.roblox_username else "не указан (команда /roblox ник)"
    send_message(chat_id, f"👤 <b>Профиль</b>\n\nTelegram ID: <code>{user.telegram_id}</code>\n"
                          f"Roblox: {roblox}\nЗаказов: {count}", keyboards.main_menu())


def cmd_orders(db, user, chat_id, _arg):
    orders = db.scalars(select(Order).where(Order.user_id == user.id)
                        .order_by(Order.id.desc()).limit(10)).all()
    if not orders:
        return send_message(chat_id, "У вас пока нет заказов.", keyboards.shop_only())
    lines = [f"<b>{o.number}</b> · {o.total_stars} ⭐ · {ORDER_STATUS_RU[o.status.value]} · "
             f"{o.created_at:%d.%m.%Y}" for o in orders]
    send_message(chat_id, "📦 <b>Последние заказы</b>\n\n" + "\n".join(lines), keyboards.shop_only())


def cmd_roblox(db, user, chat_id, arg):
    nick = (arg or "").strip()
    if not ROBLOX_RE.match(nick):
        return send_message(chat_id, "Укажите ник так: <code>/roblox Player_123</code>\n3–20 символов: латиница, цифры и _")
    user.roblox_username = nick
    db.commit()
    send_message(chat_id, f"✅ Roblox username сохранён: <code>{escape(nick)}</code>")


COMMANDS = {"start": cmd_start, "shop": cmd_shop, "help": cmd_help,
            "profile": cmd_profile, "orders": cmd_orders, "roblox": cmd_roblox}
CALLBACKS = {"orders": cmd_orders, "profile": cmd_profile, "help": cmd_help}


def process_update(db: Session, update: dict) -> str:
    """Возвращает короткое название того, что было сделано (для логов и тестов)."""
    pcq = update.get("pre_checkout_query")
    if pcq:
        from bot import payments
        return "precheckout:ok" if payments.handle_pre_checkout(db, pcq) else "precheckout:no"
    msg = update.get("message")
    if msg and msg.get("successful_payment"):
        from bot import payments
        return "payment:" + payments.handle_successful_payment(db, msg)
    if msg and msg.get("from") and msg["chat"].get("type") == "private":
        user = upsert_user(db, msg["from"])
        text = (msg.get("text") or "").strip()
        if text.startswith("/"):
            head, _, arg = text[1:].partition(" ")
            name = head.split("@")[0].lower()
            handler = COMMANDS.get(name)
            if handler:
                handler(db, user, msg["chat"]["id"], arg)
                return f"cmd:{name}"
            send_message(msg["chat"]["id"], "Неизвестная команда. /help — список команд.")
            return "cmd:unknown"
        cmd_help(db, user, msg["chat"]["id"], "")
        return "text"
    cq = update.get("callback_query")
    if cq and cq.get("from"):
        user = upsert_user(db, cq["from"])
        try:
            call("answerCallbackQuery", callback_query_id=cq["id"])
        except TelegramError:
            pass
        data = cq.get("data", "")
        if data.startswith("pay:") and data[4:].isdigit():
            from bot import payments
            o = db.get(Order, int(data[4:]))
            if o is None or o.user_id != user.id or not payments.can_pay(o):
                send_message(cq["from"]["id"], "Этот заказ нельзя оплатить.")
                return "cb:pay:no"
            payments.send_invoice(o)
            return "cb:pay"
        handler = CALLBACKS.get(data)
        if handler:
            handler(db, user, cq["from"]["id"], "")
            return f"cb:{cq['data']}"
        return "cb:unknown"
    return "ignored"


BOT_COMMANDS = [
    {"command": "start", "description": "Запуск"},
    {"command": "shop", "description": "Открыть магазин"},
    {"command": "profile", "description": "Мой профиль"},
    {"command": "orders", "description": "Мои заказы"},
    {"command": "help", "description": "Помощь"},
]


def setup_bot() -> dict:
    """Регистрирует webhook, команды и кнопку меню Mini App. Вызывается при старте при наличии токена."""
    from app.config import get_settings
    s = get_settings()
    result = {"webhook": False, "commands": False, "menu": False}
    if not s.bot_token or not s.public_url.startswith("https://"):
        return result
    try:
        call("setWebhook", url=s.public_url.rstrip("/") + "/telegram/webhook",
             secret_token=s.webhook_secret or None,
             allowed_updates=["message", "callback_query", "pre_checkout_query"])
        result["webhook"] = True
        call("setMyCommands", commands=BOT_COMMANDS)
        result["commands"] = True
        call("setChatMenuButton", menu_button={"type": "web_app", "text": "Магазин",
                                               "web_app": {"url": keyboards.miniapp_url()}})
        result["menu"] = True
    except TelegramError:
        pass
    return result

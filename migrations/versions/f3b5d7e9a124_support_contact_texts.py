"""support contact in bot welcome/help texts

Revision ID: f3b5d7e9a124
Revises: e2a4c6d8f013

Обновляет тексты только если владелец их не менял (значение равно старому стандартному).
Свои тексты из админки не трогаем.
"""
from alembic import op
import sqlalchemy as sa

revision = 'f3b5d7e9a124'
down_revision = 'e2a4c6d8f013'
branch_labels = None
depends_on = None

OLD_W = 'Привет, {name}! 👋\n\nДобро пожаловать в <b>ChapaShop</b> — магазин товаров Adopt Me с оплатой в Telegram Stars ⭐\n\nНажмите кнопку ниже, чтобы открыть магазин.'
NEW_W = 'Привет, {name}! 👋\n\nПриветствуем вас в нашем шопе <b>ChapaShop</b> — товары Adopt Me с оплатой в Telegram Stars ⭐\n\nПо любому вопросу о шопе пишите: @ChapikSupport\n\nНажмите кнопку ниже, чтобы открыть магазин.'
OLD_H = '<b>Команды</b>\n/shop — открыть магазин\n/profile — ваш профиль\n/orders — мои заказы\n/roblox <i>ник</i> — указать Roblox username\n/help — помощь\n\nПо вопросам заказа напишите сюда — продавец ответит.'
NEW_H = '<b>Команды</b>\n/shop — открыть магазин\n/profile — ваш профиль\n/orders — мои заказы\n/roblox <i>ник</i> — указать Roblox username\n/help — помощь\n\nПо любому вопросу о шопе пишите: @ChapikSupport'
OLD_C = 'Поддержка — через Telegram-бота магазина.'
NEW_C = 'По любому вопросу о шопе пишите в Telegram: @ChapikSupport'
PAIRS = [("bot_welcome", OLD_W, NEW_W), ("bot_help", OLD_H, NEW_H), ("contact_info", OLD_C, NEW_C)]


def upgrade():
    conn = op.get_bind()
    for key, old, new in PAIRS:
        conn.execute(sa.text("UPDATE settings SET value = :new WHERE key = :k AND value = :old"),
                     {"new": new, "k": key, "old": old})


def downgrade():
    conn = op.get_bind()
    for key, old, new in PAIRS:
        conn.execute(sa.text("UPDATE settings SET value = :old WHERE key = :k AND value = :new"),
                     {"new": new, "k": key, "old": old})

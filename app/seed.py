"""Демо-данные. Только вымышленные товары с пометкой «Демо»."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Category, Product, Setting
from bot.texts import DEFAULTS as BOT_TEXTS

CATEGORIES = [("pets", "Питомцы", 1), ("eggs", "Яйца", 2), ("potions", "Зелья", 3), ("other", "Другое", 4)]
PRODUCTS = [
    ("Демо-питомец «Лунный лис»", "pets", 250, "Тестовый товар для проверки магазина."),
    ("Демо-питомец «Сапфировый дракон»", "pets", 480, "Тестовый товар для проверки магазина."),
    ("Демо-яйцо «Звёздное»", "eggs", 90, "Тестовый товар для проверки магазина."),
    ("Демо-зелье «Полёт»", "potions", 60, "Тестовый товар для проверки магазина."),
    ("Демо-зелье «Неон»", "potions", 75, "Тестовый товар для проверки магазина."),
    ("Демо-набор «Новичок»", "other", 150, "Тестовый товар для проверки магазина."),
]
SETTINGS = {
    "shop_name": "ChapaShop",
    "shop_description": "Магазин товаров Adopt Me с оплатой в Telegram Stars",
    "primary_color": "#7B2FF7",
    "maintenance_mode": "0",
    "contact_info": "По любому вопросу о шопе пишите в Telegram: @ChapikSupport",
    "order_rules": "После оплаты укажите верный Roblox username. Выдача проходит на приватном сервере.",
    "bot_username": "",
}


def seed(db: Session) -> None:
    if db.scalar(select(Category).limit(1)) is None:
        cats = {}
        for slug, name, order in CATEGORIES:
            c = Category(slug=slug, name=name, sort_order=order)
            db.add(c)
            cats[slug] = c
        db.flush()
        for name, slug, price, desc in PRODUCTS:
            db.add(Product(name=name, category_id=cats[slug].id, price_stars=price,
                           description=desc, is_demo=True))
    for k, v in {**SETTINGS, **BOT_TEXTS}.items():
        if db.get(Setting, k) is None:
            db.add(Setting(key=k, value=v))
    db.commit()

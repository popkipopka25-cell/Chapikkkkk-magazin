from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Category, Product, ProductImage
from app.schemas import CategoryOut, ProductOut

router = APIRouter(prefix="/api", tags=["catalog"])
media_router = APIRouter(tags=["media"])


@media_router.get("/media/{image_id}", include_in_schema=False)
def media(image_id: int, db: Session = Depends(get_db)):
    """Фото товара из базы. Адрес с номером никогда не меняет содержимое, поэтому кеш вечный."""
    img = db.get(ProductImage, image_id)
    if img is None:
        raise HTTPException(404, "Фото не найдено")
    return Response(img.data, media_type=img.content_type,
                    headers={"Cache-Control": "public, max-age=31536000, immutable"})


@router.get("/categories", response_model=list[CategoryOut])
def categories(db: Session = Depends(get_db)):
    return db.scalars(select(Category).order_by(Category.sort_order)).all()


@router.get("/products", response_model=list[ProductOut])
def products(
    db: Session = Depends(get_db),
    q: str | None = Query(None, max_length=64),
    category: str | None = Query(None, max_length=64),
    available: bool | None = None,
    sort: Literal["new", "price_asc", "price_desc", "name"] = "new",
):
    # Параметризованные запросы SQLAlchemy — защита от SQL injection.
    stmt = select(Product).where(Product.is_hidden.is_(False))
    if q:
        stmt = stmt.where(Product.name.ilike(f"%{q.strip()}%"))
    if category:
        stmt = stmt.join(Category).where(Category.slug == category)
    if available is not None:
        stmt = stmt.where(Product.is_available.is_(available))
    order = {"new": Product.id.desc(), "price_asc": Product.price_stars.asc(),
             "price_desc": Product.price_stars.desc(), "name": Product.name.asc()}[sort]
    return db.scalars(stmt.order_by(order)).all()


@router.get("/products/{product_id}", response_model=ProductOut)
def product(product_id: int, db: Session = Depends(get_db)):
    p = db.get(Product, product_id)
    if p is None or p.is_hidden:
        raise HTTPException(404, "Товар не найден")
    return p


from app import promo as promo_mod
from app.config import get_settings
from app.models import Setting
from app.schemas import CartQuoteIn, CartQuoteOut, CartLineOut

PUBLIC_SETTINGS = ("shop_name", "shop_description", "primary_color", "maintenance_mode",
                   "contact_info", "order_rules", "bot_username")
MAX_QTY = 99
MAX_LINES = 50


@router.get("/shop")
def shop_info(db: Session = Depends(get_db)):
    """Публичные настройки магазина (без секретов)."""
    rows = db.scalars(select(Setting).where(Setting.key.in_(PUBLIC_SETTINGS))).all()
    data = {r.key: r.value for r in rows}
    data["payments_enabled"] = bool(get_settings().bot_token)  # Stars работают через бота
    return data


@router.post("/cart/quote", response_model=CartQuoteOut)
def cart_quote(body: CartQuoteIn, db: Session = Depends(get_db)):
    """Пересчёт корзины на сервере: цены берутся только из базы, не от клиента."""
    if len(body.items) > MAX_LINES:
        raise HTTPException(400, "Слишком много позиций")
    merged: dict[int, int] = {}
    for line in body.items:
        if line.quantity < 1:
            continue
        merged[line.product_id] = min(MAX_QTY, merged.get(line.product_id, 0) + line.quantity)
    out, removed, total, count = [], [], 0, 0
    products_by_id = {p.id: p for p in db.scalars(select(Product).where(Product.id.in_(merged))).all()} if merged else {}
    for pid, qty in merged.items():
        p = products_by_id.get(pid)
        if p is None or p.is_hidden:
            removed.append(pid)
            continue
        sub = p.price_stars * qty if p.is_available else 0
        out.append(CartLineOut(product_id=p.id, name=p.name, price_stars=p.price_stars, old_price_stars=p.old_price_stars,
                               quantity=qty, subtotal=sub, available=p.is_available,
                               category_id=p.category_id, image_url=p.image_url))
        if p.is_available:
            total += sub
            count += qty
    discount, applied, promo_title, promo_error = 0, None, None, None
    if body.promo_code and total > 0:
        promo, promo_error = promo_mod.find_valid(db, body.promo_code)
        if promo:
            discount, applied, promo_title = promo_mod.discount_for(promo, total), promo.code, promo.title
    return CartQuoteOut(items=out, total_stars=total - discount, count=count, removed=removed,
                        subtotal_stars=total, discount_stars=discount, promo_code=applied,
                        promo_title=promo_title, promo_error=promo_error)

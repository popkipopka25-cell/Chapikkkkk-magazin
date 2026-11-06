"""Панель владельца (Этап 6): вход, заказы, товары, покупатели, настройки, журнал."""
import hmac
import time
from datetime import datetime, timedelta, timezone
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import Response as RawResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.db import get_db
from app import promo as promo_mod
from app import stock as stock_mod
from app.slug import slugify
from app.models import (ORDER_STATUS_RU, Admin, AuditLog, Category, Order, OrderItem,
                        OrderStatus, OrderStatusHistory, Payment, Product, ProductImage, PromoCode, PromoRequest, Setting, User)
from app.security import (COOKIE, SESSION_TTL, check_session, csrf_for, hash_password,
                          make_session, parse_session, verify_password)

router = APIRouter(prefix="/admin/api", tags=["admin"])

# Ограничение попыток входа: 5 неудачных за 10 минут с одного адреса.
_fails: dict[str, deque] = defaultdict(deque)
FAIL_LIMIT, FAIL_WINDOW = 5, 600

# Ключи, которые нельзя менять через панель (секреты живут только в переменных окружения).
EDITABLE_SETTINGS_EXCLUDE = set()


def ensure_owner(db: Session) -> None:
    """Создаёт владельца из ADMIN_USERNAME/ADMIN_PASSWORD, если владельца ещё нет."""
    s = get_settings()
    if not s.admin_password or db.scalar(select(Admin).limit(1)) is not None:
        return
    db.add(Admin(username=s.admin_username, password_hash=hash_password(s.admin_password)))
    db.commit()


def audit(db: Session, actor: str, action: str, entity: str | None = None,
          entity_id=None, details: dict | None = None) -> None:
    db.add(AuditLog(actor=actor, action=action, entity=entity,
                    entity_id=None if entity_id is None else str(entity_id), details=details))


def current_admin(request: Request, db: Session = Depends(get_db)) -> Admin:
    token = request.cookies.get(COOKIE)
    parsed = parse_session(token)
    admin = db.get(Admin, parsed[0]) if parsed else None
    if admin is None or not check_session(token, admin.password_hash):
        raise HTTPException(401, "Нужен вход")
    if request.method not in ("GET", "HEAD"):
        sent = request.headers.get("X-CSRF-Token", "")
        if not hmac.compare_digest(sent, csrf_for(token)):
            raise HTTPException(403, "Неверный CSRF-токен")
    return admin


# ---------- Вход ----------
class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


def _set_cookie(resp: Response, token: str, request: Request):
    resp.set_cookie(COOKIE, token, max_age=SESSION_TTL, httponly=True, samesite="strict",
                    secure=request.url.scheme == "https", path="/admin")


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = request.client.host if request.client else "?"
    q, t = _fails[ip], time.monotonic()
    while q and t - q[0] > FAIL_WINDOW:
        q.popleft()
    if len(q) >= FAIL_LIMIT:
        raise HTTPException(429, "Слишком много попыток. Подождите 10 минут.")
    admin = db.scalar(select(Admin).where(Admin.username == body.username))
    if admin is None or not verify_password(body.password, admin.password_hash):
        q.append(t)
        audit(db, body.username[:64], "login_failed", details={"ip": ip})
        db.commit()
        raise HTTPException(401, "Неверный логин или пароль")
    q.clear()
    token, csrf = make_session(admin.id, admin.password_hash)
    _set_cookie(response, token, request)
    audit(db, admin.username, "login", details={"ip": ip})
    db.commit()
    return {"username": admin.username, "csrf": csrf}


@router.post("/logout")
def logout(response: Response, admin: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    response.delete_cookie(COOKIE, path="/admin")
    audit(db, admin.username, "logout")
    db.commit()
    return {"ok": True}


@router.get("/me")
def me(request: Request, admin: Admin = Depends(current_admin)):
    return {"username": admin.username, "csrf": csrf_for(request.cookies.get(COOKIE))}


class PasswordIn(BaseModel):
    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


@router.post("/password")
def change_password(body: PasswordIn, request: Request, response: Response,
                    admin: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    if not verify_password(body.old_password, admin.password_hash):
        raise HTTPException(400, "Старый пароль неверный")
    admin.password_hash = hash_password(body.new_password)
    audit(db, admin.username, "password_changed")
    db.commit()
    token, csrf = make_session(admin.id, admin.password_hash)
    _set_cookie(response, token, request)
    return {"ok": True, "csrf": csrf}


# ---------- Сводка ----------
@router.get("/stats")
def stats(_: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    by_status = dict(db.execute(select(Order.status, func.count()).group_by(Order.status)).all())
    ok_pay = Payment.status == "succeeded"
    revenue = db.scalar(select(func.coalesce(func.sum(Payment.amount_stars), 0)).where(ok_pay))
    paid_orders = db.scalar(select(func.count()).select_from(Order).where(
        Order.payment_status == "paid")) or 0
    now_utc = datetime.now(timezone.utc)
    today = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)

    def period(days: int):
        since = today - timedelta(days=days - 1)
        n = db.scalar(select(func.count()).select_from(Order).where(Order.created_at >= since)) or 0
        s = db.scalar(select(func.coalesce(func.sum(Payment.amount_stars), 0)).where(ok_pay, Payment.created_at >= since)) or 0
        return {"orders": n, "stars": s}

    # График за 14 дней: заказы и полученные Stars по дням (группировка в Python — одинаково в SQLite и PostgreSQL)
    since14 = today - timedelta(days=13)
    days = {(since14 + timedelta(days=i)).date().isoformat(): {"orders": 0, "stars": 0} for i in range(14)}
    for created, in db.execute(select(Order.created_at).where(Order.created_at >= since14)).all():
        k = created.date().isoformat()
        if k in days:
            days[k]["orders"] += 1
    for created, amount in db.execute(select(Payment.created_at, Payment.amount_stars).where(ok_pay, Payment.created_at >= since14)).all():
        k = created.date().isoformat()
        if k in days:
            days[k]["stars"] += amount
    top = db.execute(
        select(OrderItem.product_name, func.sum(OrderItem.quantity), func.sum(OrderItem.price_stars * OrderItem.quantity))
        .join(Order, Order.id == OrderItem.order_id).where(Order.payment_status == "paid")
        .group_by(OrderItem.product_name).order_by(func.sum(OrderItem.quantity).desc()).limit(5)).all()
    return {
        "orders_total": sum(by_status.values()),
        "by_status": {k.value if hasattr(k, "value") else k: v for k, v in by_status.items()},
        "revenue_stars": revenue,
        "customers": db.scalar(select(func.count(User.id))),
        "products": db.scalar(select(func.count(Product.id))),
        "blocked_users": db.scalar(select(func.count(User.id)).where(User.is_blocked.is_(True))) or 0,
        "paid_orders": paid_orders,
        "avg_check": round(revenue / paid_orders) if paid_orders else 0,
        "promo_uses": db.scalar(select(func.coalesce(func.sum(PromoCode.used_count), 0))) or 0,
        "promo_requests_pending": db.scalar(select(func.count(PromoRequest.id)).where(PromoRequest.status == "pending")) or 0,
        "periods": {"today": period(1), "week": period(7), "month": period(30)},
        "daily": [{"date": k, **v} for k, v in days.items()],
        "top_products": [{"name": n, "qty": int(q), "stars": int(s)} for n, q, s in top],
    }


# ---------- Заказы ----------
def order_dict(o: Order, full: bool = False) -> dict:
    d = {"id": o.id, "number": o.number, "created_at": o.created_at.isoformat(),
         "telegram_id": o.telegram_id, "roblox_username": o.roblox_username,
         "total_stars": o.total_stars, "promo_code": o.promo_code, "discount_stars": o.discount_stars or 0,
         "payment_status": o.payment_status.value,
         "status": o.status.value, "status_ru": ORDER_STATUS_RU[o.status.value],
         "server_link": o.server_link}
    if full:
        d["items"] = [{"product_id": i.product_id, "name": i.product_name, "price_stars": i.price_stars,
                       "quantity": i.quantity, "subtotal": i.price_stars * i.quantity} for i in o.items]
        d["history"] = [{"old": h.old_status, "new": h.new_status,
                         "new_ru": ORDER_STATUS_RU.get(h.new_status, h.new_status),
                         "by": h.changed_by, "comment": h.comment, "at": h.created_at.isoformat()}
                        for h in sorted(o.history, key=lambda x: x.id)]
    return d


@router.get("/orders")
def orders(_: Admin = Depends(current_admin), db: Session = Depends(get_db),
           status: str | None = None, q: str | None = None, limit: int = 100, offset: int = 0):
    stmt = select(Order).options(selectinload(Order.items))
    if status:
        if status not in ORDER_STATUS_RU:
            raise HTTPException(400, "Неизвестный статус")
        stmt = stmt.where(Order.status == OrderStatus(status))
    if q:
        q = q.strip()[:64]
        conds = [Order.roblox_username.ilike(f"%{q}%")]
        if q.lstrip("#").isdigit():
            n = int(q.lstrip("#"))
            conds += [Order.public_number == n, and_(Order.public_number.is_(None), Order.id == n), Order.telegram_id == n]
        stmt = stmt.where(or_(*conds))
    rows = db.scalars(stmt.order_by(Order.id.desc()).limit(min(max(limit, 1), 200)).offset(max(offset, 0))).all()
    out = []
    for o in rows:
        d = order_dict(o)
        d["items_preview"] = ", ".join(f"{i.product_name} ×{i.quantity}" for i in o.items)
        out.append(d)
    return out


def _get_order(db: Session, oid: int) -> Order:
    o = db.get(Order, oid)
    if o is None:
        raise HTTPException(404, "Заказ не найден")
    return o


@router.get("/orders/{oid}")
def order_detail(oid: int, _: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    o = _get_order(db, oid)
    d = order_dict(o, full=True)
    u = db.get(User, o.user_id)
    d["customer"] = ({"id": u.id, "username": u.username, "first_name": u.first_name,
                      "is_blocked": bool(u.is_blocked)} if u else None)
    vip = db.get(Setting, "vip_server_link")
    d["default_server_link"] = ((vip.value if vip else "") or "").strip() or None     # общая VIP-ссылка из настроек
    d["payments"] = [{"charge_id": p.telegram_payment_charge_id, "amount": p.amount_stars, "status": p.status,
                      "at": p.created_at.isoformat()}
                     for p in db.scalars(select(Payment).where(Payment.order_id == o.id))]
    return d


# Разрешённые переходы статусов из панели. Оплату ставит только Telegram.
TRANSITIONS = {
    "awaiting_payment": {"rejected"},
    "paid": {"processing", "awaiting_delivery", "delivered", "rejected"},
    "processing": {"awaiting_delivery", "delivered", "rejected"},
    "awaiting_delivery": {"processing", "delivered", "rejected"},
    "delivered": set(),
    "rejected": set(),
    "refunded": set(),
}


class StatusIn(BaseModel):
    status: str
    comment: str | None = Field(None, max_length=500)
    notify: bool = True


@router.post("/orders/{oid}/status")
def set_status(oid: int, body: StatusIn, admin: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    o = _get_order(db, oid)
    old = o.status.value
    if body.status not in TRANSITIONS.get(old, set()):
        raise HTTPException(400, f"Нельзя сменить «{ORDER_STATUS_RU[old]}» на «{ORDER_STATUS_RU.get(body.status, body.status)}»")
    o.history.append(OrderStatusHistory(old_status=old, new_status=body.status,
                                        changed_by=admin.username, comment=body.comment))
    o.status = OrderStatus(body.status)
    if body.status == "rejected":
        stock_mod.give_back(db, o)          # отклонённый заказ возвращает товар на склад
    audit(db, admin.username, "order_status", "order", o.id, {"from": old, "to": body.status})
    db.commit()
    sent = False
    if body.notify:
        from bot import notify
        if body.status == "rejected":
            sent = notify.rejected(db, o, body.comment)
        elif body.status == "delivered":
            sent = notify.delivered(db, o)
            notify.receipt(db, o)  # чек отправляется вместе с уведомлением о выдаче
        else:
            sent = notify.status_changed(db, o)
    return {**order_dict(o), "notified": sent}


class LinkIn(BaseModel):
    server_link: str = Field(max_length=512)
    notify: bool = True

    @field_validator("server_link")
    @classmethod
    def https_only(cls, v: str) -> str:
        v = v.strip()
        if v and not v.startswith("https://"):
            raise ValueError("Ссылка должна начинаться с https://")
        return v


@router.post("/orders/{oid}/server-link")
def set_link(oid: int, body: LinkIn, admin: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    o = _get_order(db, oid)
    o.server_link = body.server_link or None
    audit(db, admin.username, "order_server_link", "order", o.id, {"set": bool(o.server_link)})
    db.commit()
    sent = False
    if body.notify and o.server_link:
        from bot import notify
        sent = notify.server_link(db, o)
    return {**order_dict(o), "notified": sent}


@router.post("/orders/{oid}/refund")
def refund_order(oid: int, admin: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    o = _get_order(db, oid)
    if o.payment_status.value != "paid":
        raise HTTPException(400, "Заказ не оплачен — возвращать нечего")
    from bot.payments import refund
    was_delivered = o.status.value == "delivered"
    if not refund(db, o, actor=admin.username):
        raise HTTPException(400, "Платёж не найден")
    if not was_delivered:
        stock_mod.give_back(db, o)          # товар не выдан — возвращаем на склад
    audit(db, admin.username, "order_refund", "order", o.id, {"stars": o.total_stars})
    db.commit()
    from bot import notify
    notify.status_changed(db, o)
    return order_dict(o)


# ---------- Выдача и чеки (Этап 7) ----------
class DeliverIn(BaseModel):
    server_link: str = Field(min_length=1, max_length=512)
    comment: str | None = Field(None, max_length=500)

    @field_validator("server_link")
    @classmethod
    def https_only(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith("https://"):
            raise ValueError("Ссылка должна начинаться с https://")
        return v


@router.post("/orders/{oid}/deliver")
def start_delivery(oid: int, body: DeliverIn, admin: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    """Одно действие: сохранить ссылку, перевести в «Ожидает выдачи» и отправить ссылку покупателю."""
    o = _get_order(db, oid)
    old = o.status.value
    if old not in ("paid", "processing", "awaiting_delivery"):
        raise HTTPException(400, f"Выдача невозможна в статусе «{ORDER_STATUS_RU[old]}»")
    o.server_link = body.server_link
    if old != "awaiting_delivery":
        o.history.append(OrderStatusHistory(old_status=old, new_status="awaiting_delivery",
                                            changed_by=admin.username, comment=body.comment or "Отправлена ссылка на сервер"))
        o.status = OrderStatus.awaiting_delivery
    audit(db, admin.username, "order_deliver", "order", o.id, {"from": old})
    db.commit()
    from bot import notify
    return {**order_dict(o), "notified": notify.server_link(db, o)}


def _receipt_pdf(db: Session, o: Order) -> bytes:
    from app.receipt import build_receipt, can_have_receipt
    if not can_have_receipt(o):
        raise HTTPException(400, "Чек доступен только для оплаченного заказа")
    pay = db.scalar(select(Payment).where(Payment.order_id == o.id).order_by(Payment.id))
    shop = db.get(Setting, "shop_name")
    return build_receipt(o, pay, shop.value if shop and shop.value else "ChapaShop")


@router.get("/orders/{oid}/receipt.pdf")
def receipt_pdf(oid: int, download: bool = False, _: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    """PDF-чек. ?download=1 — браузер сразу сохраняет файл, иначе открывает его во вкладке."""
    o = _get_order(db, oid)
    kind = "attachment" if download else "inline"
    return RawResponse(_receipt_pdf(db, o), media_type="application/pdf",
                       headers={"Content-Disposition": f'{kind}; filename="ChapaShop_chek_{o.number}.pdf"'})


@router.post("/orders/{oid}/send-receipt")
def send_receipt(oid: int, admin: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    o = _get_order(db, oid)
    _receipt_pdf(db, o)  # проверка, что чек возможен
    from bot import notify
    sent = notify.receipt(db, o)
    audit(db, admin.username, "order_receipt_sent", "order", o.id, {"sent": sent})
    db.commit()
    return {"ok": True, "notified": sent}


# ---------- Товары ----------
class ProductIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field("", max_length=2000)
    image_url: str | None = Field(None, max_length=512)
    category_id: int | None = None
    price_stars: int = Field(ge=0, le=100000)          # цена БЕЗ скидки; 0 — бесплатный товар; скидку считает сервер
    discount_percent: int = Field(0, ge=0, le=90)
    is_available: bool = True
    is_hidden: bool = False
    is_demo: bool = False
    stock: int | None = Field(None, ge=0, le=1000000)   # сколько штук в наличии; пусто — без ограничения

    @field_validator("image_url")
    @classmethod
    def safe_url(cls, v):
        if v in (None, ""):
            return None
        v = v.strip()
        if not (v.startswith("https://") or v.startswith("/static/") or v.startswith("/media/")):
            raise ValueError("Адрес картинки должен начинаться с https://")
        return v


def pricing(base: int, percent: int) -> tuple[int, int | None]:
    """(итоговая цена, цена до скидки или None). Платный товар не бывает дешевле 1 ⭐; бесплатный остаётся 0."""
    if base <= 0:
        return 0, None
    if percent <= 0:
        return base, None
    final = max(1, round(base * (100 - percent) / 100))
    return (final, base) if final < base else (base, None)


def product_dict(p: Product) -> dict:
    return {"id": p.id, "name": p.name, "description": p.description, "image_url": p.image_url,
            "category_id": p.category_id, "price_stars": p.price_stars,
            "old_price_stars": p.old_price_stars, "discount_percent": p.discount_percent or 0,
            "base_price_stars": p.old_price_stars or p.price_stars,
            "is_available": p.is_available, "is_hidden": p.is_hidden, "is_demo": p.is_demo,
            "stock": p.stock, "in_stock": p.available_now}


def _apply(p: Product, body: ProductIn) -> dict:
    """Записывает поля в товар, возвращает {поле: [было, стало]} для журнала."""
    final, old = pricing(body.price_stars, body.discount_percent)
    new = {"name": body.name, "description": body.description, "image_url": body.image_url,
           "category_id": body.category_id, "price_stars": final, "old_price_stars": old,
           "discount_percent": body.discount_percent if old else 0,
           "is_available": body.is_available, "is_hidden": body.is_hidden, "is_demo": body.is_demo,
           "stock": body.stock}
    changes = {k: [getattr(p, k, None), v] for k, v in new.items() if getattr(p, k, None) != v}
    for k, v in new.items():
        setattr(p, k, v)
    return changes


def _drop_orphan_image(db: Session, url: str | None) -> None:
    """Удаляет загруженное фото из базы, если на него больше не ссылается ни один товар."""
    if not url or not url.startswith("/media/"):
        return
    iid = url[len("/media/"):]
    if not iid.isdigit():
        return
    still = (db.scalar(select(func.count()).select_from(Product).where(Product.image_url == url))
             + db.scalar(select(func.count()).select_from(Category).where(Category.icon == url)))
    if not still:
        img = db.get(ProductImage, int(iid))
        if img is not None:
            db.delete(img)


# ---------- Категории (игры и разделы магазина) ----------
class CategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    icon: str | None = Field(None, max_length=512)       # эмодзи или адрес картинки
    sort_order: int = Field(0, ge=-1000, le=1000)         # чем меньше число, тем левее категория

    @field_validator("name")
    @classmethod
    def clean_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Введите название категории")
        return v

    @field_validator("icon")
    @classmethod
    def clean_icon(cls, v):
        v = (v or "").strip()
        if not v:
            return None
        if v.startswith(("https://", "/static/", "/media/")):
            return v
        if len(v) <= 8 and not any(ch in v for ch in "<>\"'&"):     # короткий текст или эмодзи
            return v
        raise ValueError("Иконка: эмодзи или картинка (https://…)")


def _cat_dict(c: Category) -> dict:
    return {"id": c.id, "name": c.name, "slug": c.slug, "icon": c.icon, "sort_order": c.sort_order}


@router.post("/categories")
def create_category(body: CategoryIn, admin: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    base = slugify(body.name)
    slug, n = base, 2
    while db.scalar(select(Category.id).where(Category.slug == slug)):
        slug, n = f"{base}_{n}", n + 1
    c = Category(slug=slug, name=body.name, icon=body.icon, sort_order=body.sort_order)
    db.add(c)
    db.flush()
    audit(db, admin.username, "category_create", "category", c.id, {"name": c.name})
    db.commit()
    return _cat_dict(c)


@router.put("/categories/{cid}")
def update_category(cid: int, body: CategoryIn, admin: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    c = db.get(Category, cid)
    if c is None:
        raise HTTPException(404, "Категория не найдена")
    old_icon = c.icon
    c.name, c.icon, c.sort_order = body.name, body.icon, body.sort_order      # адрес (slug) не меняем — ссылки остаются рабочими
    if old_icon != c.icon:
        db.flush()
        _drop_orphan_image(db, old_icon)
    audit(db, admin.username, "category_update", "category", c.id, {"name": c.name})
    db.commit()
    return _cat_dict(c)


@router.delete("/categories/{cid}")
def delete_category(cid: int, admin: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    c = db.get(Category, cid)
    if c is None:
        raise HTTPException(404, "Категория не найдена")
    moved = db.execute(update(Product).where(Product.category_id == c.id).values(category_id=None)).rowcount
    icon = c.icon
    audit(db, admin.username, "category_delete", "category", c.id, {"name": c.name, "products_moved": moved})
    db.delete(c)
    db.flush()
    _drop_orphan_image(db, icon)
    db.commit()
    return {"ok": True, "products_without_category": moved}


@router.get("/products")
def admin_products(_: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    return {"products": [product_dict(p) for p in db.scalars(select(Product).order_by(Product.id.desc()))],
            "categories": [_cat_dict(c) for c in db.scalars(select(Category).order_by(Category.sort_order, Category.id))]}


def _check_cat(db: Session, cid):
    if cid is not None and db.get(Category, cid) is None:
        raise HTTPException(400, "Категория не найдена")


# --- загрузка фото из галереи ---
MAX_IMAGE_BYTES = 5 * 1024 * 1024


def _sniff_image(b: bytes) -> str | None:
    """Тип картинки определяем по первым байтам, а не по заголовку от клиента. SVG не принимаем (XSS)."""
    if b[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "image/webp"
    if b[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return None


@router.post("/upload-image")
async def upload_image(request: Request, admin: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    """Принимает сам файл картинки в теле запроса, кладёт в базу, возвращает адрес /media/<id>."""
    raw = await request.body()
    if not raw:
        raise HTTPException(400, "Файл пустой")
    if len(raw) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "Фото больше 5 МБ")
    kind = _sniff_image(raw)
    if kind is None:
        raise HTTPException(400, "Нужна картинка JPG, PNG, WEBP или GIF")
    img = ProductImage(content_type=kind, data=raw)
    db.add(img)
    db.flush()
    audit(db, admin.username, "image_upload", "image", img.id, {"bytes": len(raw)})
    db.commit()
    return {"image_url": f"/media/{img.id}"}


# --- тестовые товары для проверки магазина и бота (объявлены раньше /products/{pid}) ---
DEMO_PRODUCTS = [
    # (название, категория, цена без скидки, скидка %, описание, в наличии)
    ("Тест · Неон-дракон", "pets", 500, 0, "Тестовый товар: проверка карточки, корзины и оплаты Stars.", True),
    ("Тест · Радужный единорог", "pets", 300, 20, "Тестовый товар со скидкой 20% — проверка зачёркнутой цены.", True),
    ("Тест · Золотое яйцо", "eggs", 120, 0, "Тестовый товар: проверка заказа на малую сумму.", True),
    ("Тест · Зелье полёта", "potions", 60, 10, "Тестовый товар со скидкой 10%.", True),
    ("Тест · Набор путешественника", "other", 250, 0, "Тестовый товар: несколько штук в одном заказе.", True),
    ("Тест · Нет в наличии", "other", 99, 0, "Тестовый товар: проверка метки «Нет в наличии».", False),
]


@router.post("/demo-products")
def create_demo_products(admin: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    cats = {c.slug: c.id for c in db.scalars(select(Category))}
    have = set(db.scalars(select(Product.name).where(Product.is_demo.is_(True))))
    made = 0
    for name, slug, base, pct, desc, avail in DEMO_PRODUCTS:
        if name in have:
            continue
        final, old = pricing(base, pct)
        db.add(Product(name=name, description=desc, category_id=cats.get(slug), price_stars=final,
                       old_price_stars=old, discount_percent=pct if old else 0,
                       is_available=avail, is_demo=True))
        made += 1
    audit(db, admin.username, "demo_products_create", "product", None, {"created": made})
    db.commit()
    return {"created": made}


@router.delete("/demo-products")
def delete_demo_products(admin: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    """Удаляет только товары с пометкой «Демо». Старые заказы хранят снимок названия и цены."""
    rows = db.scalars(select(Product).where(Product.is_demo.is_(True))).all()
    urls = [p.image_url for p in rows]
    for p in rows:
        db.delete(p)
    db.flush()
    for u in set(urls):
        _drop_orphan_image(db, u)
    audit(db, admin.username, "demo_products_delete", "product", None, {"deleted": len(rows)})
    db.commit()
    return {"deleted": len(rows)}


@router.post("/products")
def create_product(body: ProductIn, admin: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    _check_cat(db, body.category_id)
    p = Product(name=body.name, price_stars=body.price_stars)
    _apply(p, body)
    db.add(p)
    db.flush()
    audit(db, admin.username, "product_create", "product", p.id, {"name": p.name, "price": p.price_stars})
    db.commit()
    return product_dict(p)


@router.put("/products/{pid}")
def update_product(pid: int, body: ProductIn, admin: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    p = db.get(Product, pid)
    if p is None:
        raise HTTPException(404, "Товар не найден")
    _check_cat(db, body.category_id)
    old_url = p.image_url
    changes = _apply(p, body)
    if old_url != p.image_url:
        db.flush()
        _drop_orphan_image(db, old_url)
    audit(db, admin.username, "product_update", "product", p.id, changes)
    db.commit()
    return product_dict(p)


@router.delete("/products/{pid}")
def delete_product(pid: int, admin: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    p = db.get(Product, pid)
    if p is None:
        raise HTTPException(404, "Товар не найден")
    # Старые заказы хранят снимок названия и цены, поэтому удаление их не ломает.
    audit(db, admin.username, "product_delete", "product", p.id, {"name": p.name})
    url = p.image_url
    db.delete(p)
    db.flush()
    _drop_orphan_image(db, url)
    db.commit()
    return {"ok": True}


# ---------- Покупатели ----------
@router.get("/customers")
def customers(_: Admin = Depends(current_admin), db: Session = Depends(get_db), q: str | None = None):
    paid = func.sum(Order.total_stars).filter(Order.payment_status == "paid")
    stmt = (select(User, func.count(Order.id), func.coalesce(paid, 0))
            .outerjoin(Order, Order.user_id == User.id).group_by(User.id).order_by(User.id.desc()))
    if q:
        q = q.strip()[:64]
        conds = [User.username.ilike(f"%{q}%"), User.roblox_username.ilike(f"%{q}%"), User.first_name.ilike(f"%{q}%")]
        if q.isdigit():
            conds.append(User.telegram_id == int(q))
        stmt = stmt.where(or_(*conds))
    return [{"id": u.id, "telegram_id": u.telegram_id, "username": u.username, "first_name": u.first_name,
             "roblox_username": u.roblox_username, "orders": n, "spent_stars": s,
             "is_blocked": bool(u.is_blocked),
             "created_at": u.created_at.isoformat()} for u, n, s in db.execute(stmt.limit(200)).all()]


@router.get("/customers/{uid}")
def customer_detail(uid: int, _: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if u is None:
        raise HTTPException(404, "Покупатель не найден")
    return {"id": u.id, "telegram_id": u.telegram_id, "username": u.username, "first_name": u.first_name,
            "roblox_username": u.roblox_username, "is_blocked": bool(u.is_blocked),
            "blocked_reason": u.blocked_reason,
            "orders": [order_dict(o) for o in db.scalars(select(Order).where(Order.user_id == u.id).order_by(Order.id.desc()))]}


class BlockIn(BaseModel):
    blocked: bool
    reason: str | None = Field(None, max_length=255)


@router.post("/customers/{uid}/block")
def block_customer(uid: int, body: BlockIn, admin: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    """Блокировка: покупатель больше не может создавать заказы и платить. Старые заказы остаются."""
    u = db.get(User, uid)
    if u is None:
        raise HTTPException(404, "Покупатель не найден")
    u.is_blocked = body.blocked
    u.blocked_reason = (body.reason or None) if body.blocked else None
    audit(db, admin.username, "user_block" if body.blocked else "user_unblock", "user", u.id,
          {"telegram_id": u.telegram_id, "reason": u.blocked_reason})
    db.commit()
    return {"id": u.id, "is_blocked": u.is_blocked, "blocked_reason": u.blocked_reason}


# ---------- Промокоды ----------
class PromoIn(BaseModel):
    code: str = Field(min_length=3, max_length=32)
    title: str | None = Field(None, max_length=64)
    percent: int | None = Field(None, ge=1, le=90)
    fixed_stars: int | None = Field(None, ge=1, le=100000)
    max_uses: int | None = Field(None, ge=1, le=1000000)
    is_active: bool = True
    growth_every: int | None = Field(None, ge=1, le=100000)     # +1% за каждые N использований
    max_percent: int | None = Field(None, ge=1, le=90)          # потолок роста

    @field_validator("code")
    @classmethod
    def clean_code(cls, v: str) -> str:
        v = promo_mod.normalize(v)
        if not promo_mod.CODE_RE.match(v):
            raise ValueError("Код: 3–32 символа, латиница, цифры, _ и -")
        return v

    @field_validator("title")
    @classmethod
    def clean_title(cls, v: str | None) -> str | None:
        v = (v or "").strip()
        return v or None


def promo_dict(p: PromoCode) -> dict:
    return {"id": p.id, "code": p.code, "title": p.title, "percent": p.percent, "fixed_stars": p.fixed_stars,
            "max_uses": p.max_uses, "used_count": p.used_count, "is_active": p.is_active,
            "growth_every": p.growth_every, "max_percent": p.max_percent,
            "percent_now": promo_mod.effective_percent(p), "created_at": p.created_at.isoformat()}


def _check_promo_kind(body: PromoIn) -> None:
    if bool(body.percent) == bool(body.fixed_stars):
        raise HTTPException(422, "Укажите либо процент, либо фиксированную скидку в Stars")


@router.get("/promos")
def list_promos(_: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    return [promo_dict(p) for p in db.scalars(select(PromoCode).order_by(PromoCode.id.desc()))]


@router.post("/promos")
def create_promo(body: PromoIn, admin: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    _check_promo_kind(body)
    if db.scalar(select(PromoCode.id).where(PromoCode.code == body.code)):
        raise HTTPException(409, "Такой промокод уже есть")
    if body.growth_every and not body.percent:
        raise HTTPException(422, "Рост скидки работает только для скидки в процентах")
    if body.max_percent and body.percent and body.max_percent < body.percent:
        raise HTTPException(422, "Максимум не может быть меньше стартовой скидки")
    p = PromoCode(code=body.code, title=body.title, percent=body.percent, fixed_stars=body.fixed_stars,
                  max_uses=body.max_uses, is_active=body.is_active,
                  growth_every=body.growth_every, max_percent=body.max_percent)
    db.add(p)
    db.flush()
    audit(db, admin.username, "promo_create", "promo", p.id, {"code": p.code})
    db.commit()
    return promo_dict(p)


@router.put("/promos/{pid}")
def update_promo(pid: int, body: PromoIn, admin: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    _check_promo_kind(body)
    p = db.get(PromoCode, pid)
    if p is None:
        raise HTTPException(404, "Промокод не найден")
    if body.code != p.code and db.scalar(select(PromoCode.id).where(PromoCode.code == body.code)):
        raise HTTPException(409, "Такой промокод уже есть")
    p.code, p.title, p.percent, p.fixed_stars = body.code, body.title, body.percent, body.fixed_stars
    p.max_uses, p.is_active = body.max_uses, body.is_active
    if "growth_every" in body.model_fields_set:      # кнопка «Выключить» эти поля не шлёт — рост сохраняется
        p.growth_every = body.growth_every
    if "max_percent" in body.model_fields_set:
        p.max_percent = body.max_percent
    audit(db, admin.username, "promo_update", "promo", p.id, {"code": p.code, "active": p.is_active})
    db.commit()
    return promo_dict(p)


@router.delete("/promos/{pid}")
def delete_promo(pid: int, admin: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    p = db.get(PromoCode, pid)
    if p is None:
        raise HTTPException(404, "Промокод не найден")
    audit(db, admin.username, "promo_delete", "promo", p.id, {"code": p.code})
    db.delete(p)      # в старых заказах остаётся текст кода — история не теряется
    db.commit()
    return {"ok": True}


# ---------- Настройки ----------
@router.get("/settings")
def get_settings_all(_: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    return {"settings": {s.key: s.value for s in db.scalars(select(Setting).order_by(Setting.key))},
            "secrets": get_settings().secrets_status()}


class SettingsIn(BaseModel):
    values: dict[str, str]


@router.put("/settings")
def put_settings(body: SettingsIn, admin: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    changed = []
    for k, v in body.values.items():
        s = db.get(Setting, k)
        if s is None:
            raise HTTPException(400, f"Неизвестная настройка: {k}")
        if len(v) > 4000:
            raise HTTPException(400, f"Слишком длинное значение: {k}")
        if k == "maintenance_mode" and v not in ("0", "1"):
            raise HTTPException(400, "maintenance_mode: 0 или 1")
        if k == "vip_server_link":
            v = v.strip()
            if v and not v.startswith("https://"):
                raise HTTPException(400, "Ссылка на VIP-сервер должна начинаться с https://")
        if s.value != v:
            s.value = v
            changed.append(k)
    audit(db, admin.username, "settings_update", "settings", None, {"keys": changed})
    db.commit()
    return {"ok": True, "changed": changed}


# ---------- Журнал ----------
@router.get("/audit")
def audit_log(_: Admin = Depends(current_admin), db: Session = Depends(get_db), limit: int = 200):
    rows = db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(min(max(limit, 1), 500)))
    return [{"id": a.id, "actor": a.actor, "action": a.action, "entity": a.entity, "entity_id": a.entity_id,
             "details": a.details, "at": a.created_at.isoformat()} for a in rows]


# ---------- Резервные копии и целостность (Этап 8) ----------
import json as _json

from app import backup as _backup
from app import integrity as _integrity

MAX_RESTORE_BYTES = 50 * 1024 * 1024


@router.get("/integrity")
def integrity(_: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    return _integrity.check(db)


@router.get("/backup")
def download_backup(admin: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    payload = _backup.make_backup(db)
    name = _backup.save_backup_file(payload)
    audit(db, admin.username, "backup_create", "backup", None, {"file": name, "counts": payload["counts"]})
    db.commit()
    body = _json.dumps(payload, ensure_ascii=False).encode()
    return RawResponse(body, media_type="application/json",
                       headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})


@router.post("/restore")
async def restore_backup(request: Request, admin: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    if request.headers.get("X-Confirm-Restore") != "YES":
        raise HTTPException(400, "Нужно подтверждение восстановления")
    raw = await request.body()
    if len(raw) > MAX_RESTORE_BYTES:
        raise HTTPException(413, "Файл слишком большой")
    try:
        payload = _json.loads(raw)
    except ValueError:
        raise HTTPException(400, "Файл не является JSON")
    try:
        _backup.validate(payload)
        # Страховка: перед заменой сохраняем текущее состояние.
        safety = _backup.save_backup_file(_backup.make_backup(db))
        counts = _backup.restore(db, payload)
    except _backup.BackupError as e:
        raise HTTPException(400, str(e))
    audit(db, admin.username, "backup_restore", "backup", None, {"counts": counts, "safety_copy": safety})
    db.commit()
    return {"ok": True, "counts": counts, "safety_copy": safety}


@router.get("/preflight")
def preflight(_: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    """Этап 9: проверка готовности к запуску (без значений секретов)."""
    from app.preflight import run_checks, summary
    return summary(run_checks(db))


# ---------- Заявки блогеров на промокод ----------
class ApproveIn(BaseModel):
    percent: int = Field(5, ge=1, le=90)           # стартовая скидка
    growth_every: int = Field(10, ge=1, le=100000)  # +1% за каждые N использований
    max_percent: int = Field(15, ge=1, le=90)       # потолок
    max_uses: int | None = Field(None, ge=1, le=1000000)


class RejectIn(BaseModel):
    comment: str | None = Field(None, max_length=255)


def request_dict(r: PromoRequest, db: Session) -> dict:
    promo = db.get(PromoCode, r.promo_id) if r.promo_id else None
    return {"id": r.id, "telegram_id": r.telegram_id, "platform": r.platform, "channel_url": r.channel_url,
            "game": r.game, "language": r.language, "code": r.code, "contact": r.contact, "status": r.status,
            "admin_comment": r.admin_comment, "created_at": r.created_at.isoformat(),
            "decided_at": r.decided_at.isoformat() if r.decided_at else None, "decided_by": r.decided_by,
            "used_count": promo.used_count if promo else None,
            "percent_now": promo_mod.effective_percent(promo) if promo else None}


def _tell_blogger(r: PromoRequest, text: str) -> None:
    try:
        from bot.telegram import send_message
        send_message(r.telegram_id, text)
    except Exception:
        pass       # сообщение не доставилось — решение всё равно сохранено


@router.get("/promo-requests")
def list_promo_requests(status: str = "pending", _: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    q = select(PromoRequest).order_by(PromoRequest.id.desc()).limit(300)
    if status in ("pending", "approved", "rejected"):
        q = q.where(PromoRequest.status == status)
    return [request_dict(r, db) for r in db.scalars(q)]


@router.post("/promo-requests/{rid}/approve")
def approve_promo_request(rid: int, body: ApproveIn, admin: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    r = db.get(PromoRequest, rid)
    if r is None:
        raise HTTPException(404, "Заявка не найдена")
    if r.status != "pending":
        raise HTTPException(409, "Заявка уже обработана")
    if body.max_percent < body.percent:
        raise HTTPException(422, "Максимум не может быть меньше стартовой скидки")
    if db.scalar(select(PromoCode.id).where(PromoCode.code == r.code)):
        raise HTTPException(409, "Такой промокод уже существует — отклоните заявку или удалите старый промокод")
    p = PromoCode(code=r.code, title="Промокод блогера", percent=body.percent, growth_every=body.growth_every,
                  max_percent=body.max_percent, max_uses=body.max_uses, is_active=True)
    db.add(p)
    db.flush()
    r.status, r.promo_id, r.decided_by, r.decided_at = "approved", p.id, admin.username, datetime.now(timezone.utc)
    audit(db, admin.username, "promo_request_approve", "promo_request", r.id, {"code": r.code})
    db.commit()
    _tell_blogger(r, f"✅ Ваша заявка одобрена!\nПромокод: <b>{r.code}</b>\n"
                     f"Скидка для покупателей: {body.percent}%, растёт на 1% за каждые {body.growth_every} "
                     f"человек, которые его ввели (до {body.max_percent}%).\n"
                     "Напоминаем: магазин не предоставляет оплату блогерам, промокод даёт скидку на товары.")
    return request_dict(r, db)


@router.post("/promo-requests/{rid}/reject")
def reject_promo_request(rid: int, body: RejectIn, admin: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    r = db.get(PromoRequest, rid)
    if r is None:
        raise HTTPException(404, "Заявка не найдена")
    if r.status != "pending":
        raise HTTPException(409, "Заявка уже обработана")
    comment = (body.comment or "").strip() or None
    r.status, r.admin_comment, r.decided_by, r.decided_at = "rejected", comment, admin.username, datetime.now(timezone.utc)
    audit(db, admin.username, "promo_request_reject", "promo_request", r.id, {"code": r.code})
    db.commit()
    _tell_blogger(r, f"❌ Заявка на промокод <b>{r.code}</b> отклонена." + (f"\nПричина: {comment}" if comment else "")
                     + "\nНовую заявку можно подать через 7 дней после предыдущей.")
    return request_dict(r, db)

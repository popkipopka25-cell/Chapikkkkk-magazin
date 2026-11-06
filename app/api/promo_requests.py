"""Заявки блогеров на личный промокод. Подаются из Mini App, личность берётся только из проверенного initData."""
import math
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import promo as promo_mod
from app.api.miniapp import current_user, ensure_not_blocked
from app.db import get_db
from app.models import PromoCode, PromoRequest, User

router = APIRouter(prefix="/api/promo-requests", tags=["promo-requests"])

COOLDOWN = timedelta(days=7)
CODE_RE = re.compile(r"^[A-Z0-9]{3,20}$")                    # только английские буквы и цифры
CONTACT_RE = re.compile(r"^@?([A-Za-z0-9_]{5,32})$")
HOSTS = {
    "tiktok": {"tiktok.com", "www.tiktok.com", "m.tiktok.com", "vm.tiktok.com"},
    "youtube": {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"},
}
GAMES = {"murder_mystery", "adopt_me"}
LANGS = {"ru", "uk", "en"}


class RequestIn(BaseModel):
    platform: str = Field(max_length=16)
    channel_url: str = Field(max_length=300)
    game: str = Field(max_length=32)
    language: str = Field(max_length=8)
    code: str = Field(max_length=40)
    contact: str = Field(max_length=40)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def clean_url(platform: str, raw: str) -> str:
    v = (raw or "").strip()
    if v and not re.match(r"^https?://", v, re.I):
        v = "https://" + v
    try:
        u = urlparse(v)
    except ValueError:
        raise HTTPException(422, "Неверная ссылка на канал")
    host = (u.hostname or "").lower()
    if u.scheme.lower() not in ("http", "https") or host not in HOSTS[platform]:
        name = "TikTok" if platform == "tiktok" else "YouTube"
        raise HTTPException(422, f"Ссылка должна вести на {name}")
    if not u.path.strip("/"):
        raise HTTPException(422, "Укажите ссылку именно на ваш канал, а не на главную страницу")
    return "https://" + host + u.path + (("?" + u.query) if u.query else "")


def clean_code(raw: str) -> str:
    v = (raw or "").strip()
    if not v.isascii():                                      # «ı», «ſ» и подобные при upper() превращаются в латиницу — не пускаем
        raise HTTPException(422, "Название промокода: только английские буквы и цифры, от 3 до 20 символов. Например, CHAPIK")
    v = v.upper()
    if not CODE_RE.match(v):
        raise HTTPException(422, "Название промокода: только английские буквы и цифры, от 3 до 20 символов. Например, CHAPIK")
    return v


def clean_contact(raw: str) -> str:
    m = CONTACT_RE.match((raw or "").strip())
    if not m:
        raise HTTPException(422, "Юзернейм в Telegram: от 5 символов, латиница, цифры и _. Например, @ChapikSupport")
    return "@" + m.group(1)


def _state(db: Session, tg_id: int) -> dict:
    last = db.scalar(select(PromoRequest).where(PromoRequest.telegram_id == tg_id).order_by(PromoRequest.id.desc()).limit(1))
    can, next_at, days_left = True, None, 0
    if last is not None:
        unlock = _aware(last.created_at) + COOLDOWN
        left = unlock - datetime.now(timezone.utc)
        if left.total_seconds() > 0:
            can, next_at, days_left = False, unlock.isoformat(), max(1, math.ceil(left.total_seconds() / 86400))
    out = {"can_apply": can, "next_at": next_at, "days_left": days_left, "last": None}
    if last is not None:
        promo = db.get(PromoCode, last.promo_id) if last.promo_id else None
        out["last"] = {"code": last.code, "status": last.status, "platform": last.platform,
                       "admin_comment": last.admin_comment, "created_at": last.created_at.isoformat(),
                       # счётчик: сколько людей ввели промокод и какая скидка сейчас
                       "used_count": promo.used_count if promo else None,
                       "percent_now": promo_mod.effective_percent(promo) if promo else None,
                       "percent_start": promo.percent if promo else None,
                       "percent_max": promo.max_percent if promo else None,
                       "growth_every": promo.growth_every if promo else None}
    return out


@router.get("/mine")
def my_state(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _state(db, user.telegram_id)


@router.post("", status_code=201)
def create_request(body: RequestIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ensure_not_blocked(user)
    st = _state(db, user.telegram_id)
    if not st["can_apply"]:
        raise HTTPException(429, f"Новую заявку можно отправить через {st['days_left']} дн. (раз в 7 дней)")
    platform = body.platform.strip().lower()
    if platform not in HOSTS:
        raise HTTPException(422, "Выберите, где вы снимаете: TikTok или YouTube")
    if body.game not in GAMES:
        raise HTTPException(422, "Выберите режим: Murder Mystery или Adopt Me")
    if body.language not in LANGS:
        raise HTTPException(422, "Выберите язык: русский, украинский или английский")
    url, code, contact = clean_url(platform, body.channel_url), clean_code(body.code), clean_contact(body.contact)
    if db.scalar(select(PromoCode.id).where(PromoCode.code == code)) or db.scalar(
            select(PromoRequest.id).where(PromoRequest.code == code, PromoRequest.status.in_(("pending", "approved")))):
        raise HTTPException(409, "Такое название промокода уже занято, придумайте другое")
    r = PromoRequest(telegram_id=user.telegram_id, platform=platform, channel_url=url, game=body.game,
                     language=body.language, code=code, contact=contact)
    db.add(r)
    db.commit()
    return _state(db, user.telegram_id)

import hmac
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from bot.handlers import process_update

router = APIRouter(tags=["telegram"])
log = logging.getLogger("chapashop.bot")


@router.post("/telegram/webhook", include_in_schema=False)
async def webhook(request: Request, db: Session = Depends(get_db),
                  x_telegram_bot_api_secret_token: str = Header(default="")):
    secret = get_settings().webhook_secret
    # Без WEBHOOK_SECRET webhook закрыт: иначе любой мог бы слать поддельные обновления.
    if not secret or not hmac.compare_digest(x_telegram_bot_api_secret_token, secret):
        raise HTTPException(401, "unauthorized")
    try:
        update = await request.json()
    except Exception:
        raise HTTPException(400, "bad json")
    try:
        process_update(db, update)
    except Exception:
        log.exception("Ошибка обработки обновления")
    # Всегда 200, чтобы Telegram не повторял одно и то же обновление бесконечно.
    return {"ok": True}

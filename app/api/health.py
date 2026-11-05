from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db

router = APIRouter(tags=["system"])


@router.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    s = get_settings()
    return {"status": "ok", "env": s.app_env, "database": "ok",
            "secrets_configured": s.secrets_status(),
            "telegram_mode": "live" if s.bot_token else "test (бот не подключён)"}

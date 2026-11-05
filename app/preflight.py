"""Этап 9: предстартовая проверка. Запуск: python -m app.preflight"""
import sys

from sqlalchemy import func, select, text

from app.config import get_settings


def run_checks(db=None) -> list[dict]:
    s = get_settings()
    prod = s.app_env == "production"
    out = []

    def add(key, ok, msg, critical=True):
        out.append({"key": key, "ok": bool(ok), "critical": critical and prod, "message": msg})

    add("SECRET_KEY", s.secret_key not in ("", "dev-insecure-key", "change-me-to-long-random-string")
        and len(s.secret_key) >= 32, "Секретный ключ длинный и не стандартный")
    add("ADMIN_PASSWORD", len(s.admin_password) >= 10, "Пароль владельца не короче 10 символов")
    add("BOT_TOKEN", ":" in s.bot_token, "Токен бота задан")
    add("WEBHOOK_SECRET", len(s.webhook_secret) >= 16, "Секрет webhook задан")
    add("PUBLIC_URL", s.public_url.startswith("https://"), "Адрес сайта начинается с https://")
    add("DATABASE", not s.db_url.startswith("sqlite") or not prod,
        "В рабочем режиме используется PostgreSQL")
    if db is not None:
        try:
            db.execute(text("SELECT 1"))
            from app.models import Product
            n = db.scalar(select(func.count()).select_from(Product)) or 0
            add("DB_CONNECT", True, "База отвечает")
            add("PRODUCTS", n > 0, f"Товаров в базе: {n}", critical=False)
        except Exception:
            add("DB_CONNECT", False, "База не отвечает")
    return out


def summary(checks: list[dict]) -> dict:
    blockers = [c["key"] for c in checks if not c["ok"] and c["critical"]]
    warnings = [c["key"] for c in checks if not c["ok"] and not c["critical"]]
    return {"ready": not blockers, "blockers": blockers, "warnings": warnings, "checks": checks}


def main() -> int:
    from app.db import SessionLocal
    with SessionLocal() as db:
        res = summary(run_checks(db))
    for c in res["checks"]:
        print(("OK  " if c["ok"] else "НЕТ ") + f"{c['key']}: {c['message']}")
    print("ГОТОВ К ЗАПУСКУ" if res["ready"] else "НЕ ГОТОВ: " + ", ".join(res["blockers"]))
    return 0 if res["ready"] else 1


if __name__ == "__main__":
    sys.exit(main())

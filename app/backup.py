"""Резервные копии (Этап 8): выгрузка всей базы в JSON с контрольной суммой и восстановление.

Таблица admins (хеши паролей) в копию НЕ попадает и при восстановлении не трогается —
владелец не потеряет доступ, а файл копии не содержит секретов.
"""
import base64
import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import DateTime, Date, LargeBinary, delete, func, insert, select, text
from sqlalchemy.orm import Session

from app.db import Base
import app.models  # noqa: F401

FORMAT = "chapashop-backup"
VERSION = 1
EXCLUDE = {"admins"}
BACKUP_DIR = Path(__file__).resolve().parent.parent / "backups"
KEEP_FILES = 10


class BackupError(ValueError):
    pass


def _tables():
    return [t for t in Base.metadata.sorted_tables if t.name not in EXCLUDE]


def _enc(v):
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, bytes):
        return base64.b64encode(v).decode()
    if hasattr(v, "value"):  # Enum
        return v.value
    return v


def _checksum(data: dict) -> str:
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def _schema_rev(db: Session) -> str | None:
    try:
        return db.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except Exception:
        db.rollback()
        return None


def make_backup(db: Session) -> dict:
    data = {}
    for t in _tables():
        rows = db.execute(select(t).order_by(*t.primary_key.columns)).mappings().all()
        data[t.name] = [{k: _enc(v) for k, v in r.items()} for r in rows]
    return {"format": FORMAT, "version": VERSION, "created_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z",
            "schema_revision": _schema_rev(db), "counts": {k: len(v) for k, v in data.items()},
            "checksum": _checksum(data), "data": data}


def save_backup_file(payload: dict) -> str:
    BACKUP_DIR.mkdir(exist_ok=True)
    name = "chapashop_" + datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y%m%d_%H%M%S") + ".json"
    (BACKUP_DIR / name).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    files = sorted(BACKUP_DIR.glob("chapashop_*.json"))
    for old in files[:-KEEP_FILES]:
        old.unlink(missing_ok=True)
    return name


def validate(payload) -> dict:
    if not isinstance(payload, dict) or payload.get("format") != FORMAT:
        raise BackupError("Это не файл резервной копии ChapaShop")
    if payload.get("version") != VERSION:
        raise BackupError("Неподдерживаемая версия копии")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise BackupError("В копии нет данных")
    if _checksum(data) != payload.get("checksum"):
        raise BackupError("Контрольная сумма не совпала — файл повреждён или изменён")
    known = {t.name: t for t in _tables()}
    for name, rows in data.items():
        if name not in known:
            raise BackupError(f"Неизвестная таблица в копии: {name}")
        if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
            raise BackupError(f"Повреждена таблица {name}")
        cols = set(known[name].columns.keys())
        for r in rows:
            extra = set(r) - cols
            if extra:
                raise BackupError(f"Лишние поля в {name}: {', '.join(sorted(extra))}")
    return data


def _dec(col, v):
    if v is None:
        return None
    if isinstance(col.type, DateTime):
        return datetime.fromisoformat(v)
    if isinstance(col.type, Date):
        return date.fromisoformat(v)
    if isinstance(col.type, LargeBinary):
        return base64.b64decode(v)
    return v


def restore(db: Session, payload) -> dict:
    """Полная замена данных одной транзакцией: при любой ошибке база остаётся как была."""
    data = validate(payload)
    tables = _tables()
    try:
        for t in reversed(tables):
            db.execute(delete(t))
        for t in tables:
            rows = data.get(t.name, [])
            if rows:
                db.execute(insert(t), [{k: _dec(t.c[k], v) for k, v in r.items()} for r in rows])
        db.flush()
        _fix_sequences(db, tables)
        db.commit()
    except BackupError:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise BackupError(f"Не удалось восстановить: {type(e).__name__}") from None
    return {t.name: len(data.get(t.name, [])) for t in tables}


def _fix_sequences(db: Session, tables):
    """PostgreSQL: после вставки с явными id сдвигаем счётчики, иначе новые записи упадут."""
    if db.get_bind().dialect.name != "postgresql":
        return
    for t in tables:
        pk = list(t.primary_key.columns)
        if len(pk) == 1 and pk[0].autoincrement and str(pk[0].type) in ("INTEGER", "BIGINT"):
            mx = db.execute(select(func.max(pk[0]))).scalar()
            if mx:
                db.execute(text("SELECT setval(pg_get_serial_sequence(:t, :c), :v)"),
                           {"t": t.name, "c": pk[0].name, "v": mx})

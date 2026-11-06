import logging
from logging.config import fileConfig

from alembic import context
from app.config import get_settings
from app.db import Base, make_engine
import app.models  # noqa: F401

# Логи Alembic видны в Render: какая миграция идёт и на чём остановилась.
if context.config.config_file_name:
    fileConfig(context.config.config_file_name, disable_existing_loggers=False)
logging.getLogger("alembic").setLevel(logging.INFO)

target_metadata = Base.metadata


def run():
    url = get_settings().db_url
    engine = make_engine(url)
    with engine.connect() as conn:
        if url.startswith("postgresql"):
            # Если таблицу держит старая версия сайта, миграция не будет висеть вечно, а упадёт с понятной ошибкой.
            conn.exec_driver_sql("SET lock_timeout = '30s'")
            conn.commit()
        context.configure(connection=conn, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


run()

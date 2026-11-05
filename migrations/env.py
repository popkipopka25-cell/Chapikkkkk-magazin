from alembic import context
from app.config import get_settings
from app.db import Base, make_engine
import app.models  # noqa: F401

target_metadata = Base.metadata


def run():
    engine = make_engine(get_settings().db_url)
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


run()

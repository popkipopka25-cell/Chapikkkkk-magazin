"""categories: icon column + game sections (Adopt Me, MM2, accounts)

Revision ID: d1e3a5c7f912
Revises: c9d1f3a5b789
"""
from alembic import op
import sqlalchemy as sa

revision = 'd1e3a5c7f912'
down_revision = 'c9d1f3a5b789'
branch_labels = None
depends_on = None

GAMES = [("adopt_me", "Adopt Me", -30), ("mm2", "Murder Mystery 2", -20), ("accounts", "Accounts", -10)]


def upgrade():
    with op.batch_alter_table('categories', schema=None) as b:
        b.add_column(sa.Column('icon', sa.String(length=512), nullable=True))
    cats = sa.table('categories', sa.column('slug', sa.String), sa.column('name', sa.String),
                    sa.column('sort_order', sa.Integer), sa.column('icon', sa.String))
    bind = op.get_bind()
    for slug, name, order in GAMES:          # добавляем, только если такой категории ещё нет
        if bind.execute(sa.select(cats.c.slug).where(cats.c.slug == slug)).first() is None:
            bind.execute(cats.insert().values(slug=slug, name=name, sort_order=order, icon=f"/static/cat/{slug}.svg"))


def downgrade():
    with op.batch_alter_table('categories', schema=None) as b:
        b.drop_column('icon')

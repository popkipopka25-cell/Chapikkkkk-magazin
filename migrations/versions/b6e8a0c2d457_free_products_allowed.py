"""free products: allow price_stars = 0 (was >= 1)

Revision ID: b6e8a0c2d457
Revises: a5d7f9b1c346
"""
from alembic import op
import sqlalchemy as sa

revision = 'b6e8a0c2d457'
down_revision = 'a5d7f9b1c346'
branch_labels = None
depends_on = None


def upgrade():
    names = {c.get('name') for c in sa.inspect(op.get_bind()).get_check_constraints('products')}
    with op.batch_alter_table('products', schema=None) as b:
        if 'ck_price_positive' in names:
            b.drop_constraint('ck_price_positive', type_='check')
        if 'ck_price_nonneg' not in names:
            b.create_check_constraint('ck_price_nonneg', 'price_stars >= 0')


def downgrade():
    with op.batch_alter_table('products', schema=None) as b:
        b.drop_constraint('ck_price_nonneg', type_='check')
        b.create_check_constraint('ck_price_positive', 'price_stars >= 1')

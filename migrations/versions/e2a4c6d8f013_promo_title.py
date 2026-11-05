"""promo code title

Revision ID: e2a4c6d8f013
Revises: d8e52b7f1c33
"""
from alembic import op
import sqlalchemy as sa

revision = 'e2a4c6d8f013'
down_revision = 'd8e52b7f1c33'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('promo_codes', schema=None) as b:
        b.add_column(sa.Column('title', sa.String(length=64), nullable=True))


def downgrade():
    with op.batch_alter_table('promo_codes', schema=None) as b:
        b.drop_column('title')

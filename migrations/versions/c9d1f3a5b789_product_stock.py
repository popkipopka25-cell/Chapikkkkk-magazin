"""product stock (how many items are in stock)

Revision ID: c9d1f3a5b789
Revises: b6e8a0c2d457
"""
from alembic import op
import sqlalchemy as sa

revision = 'c9d1f3a5b789'
down_revision = 'b6e8a0c2d457'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('products', schema=None) as b:
        b.add_column(sa.Column('stock', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('products', schema=None) as b:
        b.drop_column('stock')

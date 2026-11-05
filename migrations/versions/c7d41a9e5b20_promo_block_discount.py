"""promo codes, user blocking, order discount

Revision ID: c7d41a9e5b20
Revises: b35f2b432cf9
"""
from alembic import op
import sqlalchemy as sa

revision = 'c7d41a9e5b20'
down_revision = 'b35f2b432cf9'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('promo_codes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(length=32), nullable=False),
        sa.Column('percent', sa.Integer(), nullable=True),
        sa.Column('fixed_stars', sa.Integer(), nullable=True),
        sa.Column('max_uses', sa.Integer(), nullable=True),
        sa.Column('used_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='1', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'))
    with op.batch_alter_table('promo_codes', schema=None) as b:
        b.create_index(b.f('ix_promo_codes_code'), ['code'], unique=True)
    with op.batch_alter_table('users', schema=None) as b:
        b.add_column(sa.Column('is_blocked', sa.Boolean(), server_default='0', nullable=False))
        b.add_column(sa.Column('blocked_reason', sa.String(length=255), nullable=True))
    with op.batch_alter_table('orders', schema=None) as b:
        b.add_column(sa.Column('promo_code', sa.String(length=32), nullable=True))
        b.add_column(sa.Column('discount_stars', sa.Integer(), server_default='0', nullable=False))


def downgrade():
    with op.batch_alter_table('orders', schema=None) as b:
        b.drop_column('discount_stars')
        b.drop_column('promo_code')
    with op.batch_alter_table('users', schema=None) as b:
        b.drop_column('blocked_reason')
        b.drop_column('is_blocked')
    with op.batch_alter_table('promo_codes', schema=None) as b:
        b.drop_index(b.f('ix_promo_codes_code'))
    op.drop_table('promo_codes')

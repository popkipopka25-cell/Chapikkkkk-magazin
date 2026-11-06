"""public order numbers, growing promo discount, promo requests

Revision ID: a5d7f9b1c346
Revises: f3b5d7e9a124
"""
from alembic import op
import sqlalchemy as sa

revision = 'a5d7f9b1c346'
down_revision = 'f3b5d7e9a124'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('orders', schema=None) as b:
        b.add_column(sa.Column('public_number', sa.Integer(), nullable=True))
        b.create_index('ix_orders_public_number', ['public_number'], unique=True)
    with op.batch_alter_table('promo_codes', schema=None) as b:
        b.add_column(sa.Column('growth_every', sa.Integer(), nullable=True))
        b.add_column(sa.Column('max_percent', sa.Integer(), nullable=True))
    op.create_table(
        'promo_requests',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('telegram_id', sa.BigInteger(), nullable=False),
        sa.Column('platform', sa.String(16), nullable=False),
        sa.Column('channel_url', sa.String(300), nullable=False),
        sa.Column('game', sa.String(32), nullable=False),
        sa.Column('language', sa.String(8), nullable=False),
        sa.Column('code', sa.String(20), nullable=False),
        sa.Column('contact', sa.String(40), nullable=False),
        sa.Column('status', sa.String(16), nullable=False, server_default='pending'),
        sa.Column('admin_comment', sa.String(255), nullable=True),
        sa.Column('promo_id', sa.Integer(), sa.ForeignKey('promo_codes.id', ondelete='SET NULL'), nullable=True),
        sa.Column('decided_by', sa.String(64), nullable=True),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_promo_requests_telegram_id', 'promo_requests', ['telegram_id'])
    op.create_index('ix_promo_requests_code', 'promo_requests', ['code'])
    op.create_index('ix_promo_requests_status', 'promo_requests', ['status'])
    op.create_index('ix_promo_requests_created_at', 'promo_requests', ['created_at'])


def downgrade():
    op.drop_table('promo_requests')
    with op.batch_alter_table('promo_codes', schema=None) as b:
        b.drop_column('max_percent')
        b.drop_column('growth_every')
    with op.batch_alter_table('orders', schema=None) as b:
        b.drop_index('ix_orders_public_number')
        b.drop_column('public_number')

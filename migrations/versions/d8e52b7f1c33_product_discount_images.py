"""product discount fields and uploaded images

Revision ID: d8e52b7f1c33
Revises: c7d41a9e5b20
"""
from alembic import op
import sqlalchemy as sa

revision = 'd8e52b7f1c33'
down_revision = 'c7d41a9e5b20'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('product_images',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('content_type', sa.String(length=32), nullable=False),
        sa.Column('data', sa.LargeBinary(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'))
    with op.batch_alter_table('products', schema=None) as b:
        b.add_column(sa.Column('old_price_stars', sa.Integer(), nullable=True))
        b.add_column(sa.Column('discount_percent', sa.Integer(), server_default='0', nullable=False))


def downgrade():
    with op.batch_alter_table('products', schema=None) as b:
        b.drop_column('discount_percent')
        b.drop_column('old_price_stars')
    op.drop_table('product_images')

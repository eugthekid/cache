"""add inventory_items.manual and sales table

Revision ID: c41d7e2a9b05
Revises: 191817c9784c
Create Date: 2026-10-06 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c41d7e2a9b05'
down_revision: Union[str, Sequence[str], None] = '191817c9784c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'inventory_items',
        sa.Column('manual', sa.Boolean(), nullable=False, server_default=sa.text('0')),
    )
    op.create_table(
        'sales',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('product_id', sa.String(), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('unit_price', sa.Float(), nullable=False),
        sa.Column('unit_cost', sa.Float(), nullable=True),
        sa.Column('platform', sa.String(), nullable=True),
        sa.Column('sold_at', sa.DateTime(), nullable=False),
        sa.Column('item_costs', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['product_id'], ['products.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('sales')
    op.drop_column('inventory_items', 'manual')

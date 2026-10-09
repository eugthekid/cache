"""add inventory_items.retailer for units added by hand

Revision ID: d63f9a1c4e27
Revises: c41d7e2a9b05
Create Date: 2026-10-08 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd63f9a1c4e27'
down_revision: Union[str, Sequence[str], None] = 'c41d7e2a9b05'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('inventory_items', sa.Column('retailer', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('inventory_items', 'retailer')

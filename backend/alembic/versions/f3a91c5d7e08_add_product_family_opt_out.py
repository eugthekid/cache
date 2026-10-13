"""add products.family_opt_out

Revision ID: f3a91c5d7e08
Revises: e74a0b2d5c38
Create Date: 2026-10-13 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f3a91c5d7e08'
down_revision: Union[str, Sequence[str], None] = 'e74a0b2d5c38'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'products',
        sa.Column('family_opt_out', sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column('products', 'family_opt_out')

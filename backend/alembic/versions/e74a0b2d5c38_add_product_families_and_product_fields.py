"""add product families, product_type and variant_kind

Revision ID: e74a0b2d5c38
Revises: d63f9a1c4e27
Create Date: 2026-10-13 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e74a0b2d5c38'
down_revision: Union[str, Sequence[str], None] = 'd63f9a1c4e27'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'product_families',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.add_column('products', sa.Column('product_type', sa.String(), nullable=True))
    op.add_column('products', sa.Column('family_id', sa.String(), nullable=True))
    op.add_column('products', sa.Column('variant_kind', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('products', 'variant_kind')
    op.drop_column('products', 'family_id')
    op.drop_column('products', 'product_type')
    op.drop_table('product_families')

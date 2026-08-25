"""add catalog products and match state

Revision ID: aa112939b25c
Revises: be7de19a585d
Create Date: 2026-08-25 11:02:30.404029

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'aa112939b25c'
down_revision: Union[str, Sequence[str], None] = 'be7de19a585d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "catalog_products",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False, server_default="tcgtracking"),
        sa.Column("external_id", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("set_name", sa.String(), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("normalized_key", sa.String(), nullable=False),
        sa.Column("image_url", sa.String(), nullable=True),
        sa.Column("synced_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "external_id", name="uq_catalog_source_external"),
    )
    op.add_column(
        "products",
        sa.Column("catalog_match_status", sa.String(), nullable=False, server_default="none"),
    )
    op.add_column("products", sa.Column("catalog_product_id", sa.String(), nullable=True))
    op.add_column("products", sa.Column("catalog_rejected_id", sa.String(), nullable=True))
    op.add_column("orders", sa.Column("thumbnail_url", sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("orders", "thumbnail_url")
    op.drop_column("products", "catalog_rejected_id")
    op.drop_column("products", "catalog_product_id")
    op.drop_column("products", "catalog_match_status")
    op.drop_table("catalog_products")

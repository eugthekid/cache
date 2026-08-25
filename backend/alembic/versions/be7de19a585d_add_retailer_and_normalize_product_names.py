"""add retailer and normalize product names

Revision ID: be7de19a585d
Revises: 2d2b9d8f66c3
Create Date: 2026-08-24 19:20:16.274520

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'be7de19a585d'
down_revision: Union[str, Sequence[str], None] = '2d2b9d8f66c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Adds `retailer` and backfills it, and cleans the bot noise out of
    existing product names. Both are pure derivations of data already in
    the row, done in Python (not SQL) so they use the exact same functions
    ingestion uses -- one implementation, no drift between history and
    anything arriving from now on.
    """
    op.add_column("orders", sa.Column("retailer", sa.String(), nullable=True))

    from app import products, retailers

    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, site, raw_product_text FROM orders")).fetchall()
    for row_id, site, product_text in rows:
        retailer = retailers.display_name(site)
        cleaned = products.display_name(product_text) if product_text else None
        conn.execute(
            sa.text("UPDATE orders SET retailer = :r, raw_product_text = :p WHERE id = :i"),
            {"r": retailer, "p": cleaned or product_text, "i": row_id},
        )


def downgrade() -> None:
    """Downgrade schema.

    Product names are not un-cleaned: the originals are still in
    ingested_messages.payload, so nothing is lost, and re-dirtying them
    would be busywork.
    """
    op.drop_column("orders", "retailer")

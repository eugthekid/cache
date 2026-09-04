"""add carrier, tracking detail and shipping alert fields

Revision ID: 5a5d5879358c
Revises: 8b37dfcbf79b
Create Date: 2026-09-03 23:16:30.321429

NOTE: --autogenerate also proposed a NOT NULL on ingested_messages.payload
and three create_foreign_key calls (inventory_items.product_id,
orders.product_id, products.catalog_product_id). Those are pre-existing
drift between the models and the live schema, unrelated to this change, and
they have been REMOVED from this migration on purpose: SQLite can't add a
foreign key in place (Alembic has to rebuild and copy the whole table for
it), so folding an unrelated, riskier operation into an additive column
migration would turn a trivial change into one that rewrites four tables.
If that drift is worth closing, it belongs in its own migration.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '5a5d5879358c'
down_revision: Union[str, Sequence[str], None] = '8b37dfcbf79b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('orders', sa.Column('carrier', sa.String(), nullable=True))
    op.add_column('orders', sa.Column('estimated_delivery', sa.String(), nullable=True))
    op.add_column('orders', sa.Column('tracking_detail', sa.String(), nullable=True))
    op.add_column('orders', sa.Column('tracking_checked_at', sa.DateTime(), nullable=True))
    op.add_column('orders', sa.Column('shipping_alert_at', sa.DateTime(), nullable=True))
    op.add_column('orders', sa.Column('shipping_alert_seen_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('orders', 'shipping_alert_seen_at')
    op.drop_column('orders', 'shipping_alert_at')
    op.drop_column('orders', 'tracking_checked_at')
    op.drop_column('orders', 'tracking_detail')
    op.drop_column('orders', 'estimated_delivery')
    op.drop_column('orders', 'carrier')

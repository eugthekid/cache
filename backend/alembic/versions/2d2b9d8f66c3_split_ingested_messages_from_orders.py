"""split ingested messages from orders

Revision ID: 2d2b9d8f66c3
Revises: 1b361b829d55
Create Date: 2026-08-24 16:39:09.558942

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2d2b9d8f66c3'
down_revision: Union[str, Sequence[str], None] = '1b361b829d55'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "ingested_messages",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("source_id", sa.String(), nullable=False),
        sa.Column("external_id", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("dismissed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", "external_id", name="uq_ingested_source_external"),
    )

    # Backfill one message per existing order. This is a pure data move, not
    # a reinterpretation: every order already carried the (source_id,
    # external_id, raw_json) that a message row is made of, plus a
    # deleted_at whose exact meaning ("seen, deliberately not tracked") is
    # what dismissed_at now holds.
    # Backfill one message per existing order. The payload must be the
    # WHOLE order, not just its raw_json: status/failure_reason/etc are
    # derived at parse time and appear nowhere in raw_json, so rebuilding
    # from raw_json alone would resurrect every failed order as a success.
    op.execute(
        """
        INSERT INTO ingested_messages
            (id, user_id, source_id, external_id, payload, occurred_at,
             first_seen_at, dismissed_at)
        SELECT
            lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' ||
            substr(lower(hex(randomblob(2))), 2) || '-a' ||
            substr(lower(hex(randomblob(2))), 2) || '-' || lower(hex(randomblob(6))),
            user_id, source_id, external_id,
            json_object(
                'source_id',        source_id,
                'external_id',      external_id,
                'status',           status,
                'failure_reason',   failure_reason,
                'raw_product_text', raw_product_text,
                'profile',          profile,
                'site',             site,
                'module',           module,
                'category',         category,
                'quantity',         quantity,
                'unit_price',       unit_price,
                'currency',         COALESCE(currency, 'USD'),
                'order_number',     order_number,
                'order_url',        order_url,
                'shipping_status',  COALESCE(shipping_status, 'not_shipped'),
                'tracking_number',  tracking_number,
                'ship_to_label',    ship_to_label,
                'ship_to_address',  ship_to_address,
                'purchased_at',     purchased_at,
                -- json() so the nested object embeds as JSON rather than
                -- as a quoted string, which Pydantic rejects on replay.
                'raw_json',         json(COALESCE(NULLIF(raw_json, ''), '{}'))
            ),
            purchased_at,
            COALESCE(created_at, CURRENT_TIMESTAMP), deleted_at
        FROM orders
        """
    )

    # Tombstoned orders have now been fully represented as dismissed
    # messages, so the ghost rows they left in the user's orders table (and
    # the units they spawned) can finally go for real.
    op.execute(
        "DELETE FROM inventory_items WHERE order_id IN (SELECT id FROM orders WHERE deleted_at IS NOT NULL)"
    )
    op.execute("DELETE FROM orders WHERE deleted_at IS NOT NULL")

    with op.batch_alter_table("orders") as batch:
        batch.drop_column("deleted_at")


def downgrade() -> None:
    """Downgrade schema."""
    # Deleted orders cannot be resurrected here -- the rows were removed on
    # upgrade and only their messages remain. Restoring the column gives
    # every surviving order the "live" state it actually has.
    with op.batch_alter_table("orders") as batch:
        batch.add_column(sa.Column("deleted_at", sa.DateTime(), nullable=True))
    op.drop_table("ingested_messages")

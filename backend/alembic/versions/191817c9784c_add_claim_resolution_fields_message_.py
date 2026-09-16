"""add claim resolution fields: message order_id, order user_overrides and external_sku

Revision ID: 191817c9784c
Revises: 5a5d5879358c
Create Date: 2026-09-16

Groundwork for multi-source ingestion (see docs/DATA-MODEL.md). An order
stops being a row OWNED by whichever source happened to report it first,
and becomes the resolution of every CLAIM made about that purchase --
Discord webhook, retailer email, spreadsheet row, or the user's own edit.

Three additive columns, no data migration beyond one backfill:

  ingested_messages.order_id
      Which order this message resolved into. Without it there is no way
      to ask "what claims produced this row", which is what forces the
      resolver to keep a denormalized provenance blob instead of deriving
      from the message log we already store. Backfilled below from the
      (source_id, external_id) pair both tables already share, so history
      becomes queryable immediately.

  orders.user_overrides
      Fields the user edited by hand, as {field: value}. Applied AFTER
      claim resolution so a correction always wins and, crucially,
      survives re-resolution -- an auto-syncing ledger that silently
      reverts a hand-fixed price is one people stop trusting. NULL is
      read as {} rather than given a server_default: SQLite's handling of
      defaults on ALTER is fiddly, and the resolver has to tolerate a
      missing value anyway.

  orders.external_sku
      The retailer's own SKU for this line. Nothing populates it yet --
      it arrives with email parsing -- but it is the strongest available
      key for matching a cart line across sources (verified in real
      Pokemon Center mail: every confirmation, shipping and cancellation
      email carries "SKU #: 10-10449-122" per line). Added now so the
      matcher can prefer it from the start rather than needing a second
      migration once the parser exists.

Deliberately NOT added: a fulfillment/shipment id for split shipments.
Pokemon Center's shipping mail does carry one ("Fulfillment ID: 22746525")
and split shipments are real, but the right shape for that depends on
whether a single line can split across boxes -- unknown until the parser
is running. Guessing it now would be schema we'd have to migrate away from.

No foreign key on ingested_messages.order_id, matching the reasoning in
revision 5a5d5879358c: SQLite cannot add a constraint in place, so Alembic
would rebuild and copy the whole table for it. This codebase already
carries the same deliberate drift on orders.product_id and
inventory_items.product_id.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "191817c9784c"
down_revision: Union[str, Sequence[str], None] = "5a5d5879358c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ingested_messages", sa.Column("order_id", sa.String(), nullable=True))
    op.add_column("orders", sa.Column("user_overrides", sa.JSON(), nullable=True))
    op.add_column("orders", sa.Column("external_sku", sa.String(), nullable=True))

    # Backfill the link for every message that already produced an order.
    # Both tables carry (source_id, external_id) and it is UNIQUE on each,
    # so this pairing is exact -- no guessing, and it can be re-run safely.
    op.execute(
        """
        UPDATE ingested_messages
           SET order_id = (
               SELECT o.id FROM orders o
                WHERE o.source_id = ingested_messages.source_id
                  AND o.external_id = ingested_messages.external_id
           )
         WHERE order_id IS NULL
        """
    )

    op.create_index(
        "ix_ingested_messages_order_id", "ingested_messages", ["order_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_ingested_messages_order_id", table_name="ingested_messages")
    op.drop_column("orders", "external_sku")
    op.drop_column("orders", "user_overrides")
    op.drop_column("ingested_messages", "order_id")

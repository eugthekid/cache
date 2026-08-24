"""add soft delete and money_received_at

Revision ID: be430bdd6b52
Revises: 9b0fecfeda6e
Create Date: 2026-08-23 23:26:53.226837

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'be430bdd6b52'
down_revision: Union[str, Sequence[str], None] = '9b0fecfeda6e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    All three columns are nullable with no server_default: NULL is the
    meaningful "not deleted" / "not yet paid" state, so existing rows are
    correct as-is and need no backfill.
    """
    op.add_column("orders", sa.Column("deleted_at", sa.DateTime(), nullable=True))
    op.add_column("inventory_items", sa.Column("deleted_at", sa.DateTime(), nullable=True))
    op.add_column(
        "inventory_items", sa.Column("money_received_at", sa.DateTime(), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("inventory_items", "money_received_at")
    op.drop_column("inventory_items", "deleted_at")
    op.drop_column("orders", "deleted_at")

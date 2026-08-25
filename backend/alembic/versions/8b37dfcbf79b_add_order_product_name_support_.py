"""add order product_name support, inventory location

Revision ID: 8b37dfcbf79b
Revises: aa112939b25c
Create Date: 2026-08-25 13:20:29.508301

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8b37dfcbf79b'
down_revision: Union[str, Sequence[str], None] = 'aa112939b25c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("inventory_items", sa.Column("location", sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("inventory_items", "location")

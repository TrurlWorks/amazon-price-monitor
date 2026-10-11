"""Persist the selected dashboard layout."""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "runtime_settings",
        sa.Column("display_mode", sa.String(), nullable=False, server_default="tiles"),
    )


def downgrade() -> None:
    op.drop_column("runtime_settings", "display_mode")

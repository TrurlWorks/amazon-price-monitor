"""Persist queued product refresh requests."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "refresh_requests",
        sa.Column(
            "product_id", sa.Integer(),
            sa.ForeignKey("products.id", ondelete="CASCADE"), primary_key=True,
        ),
        sa.Column("requested_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("refresh_requests")

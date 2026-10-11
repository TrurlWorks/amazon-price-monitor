"""Record acquisition outcomes and persist one-shot schedule overrides."""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("refresh_requests", sa.Column("override_at", sa.DateTime(), nullable=True))
    op.create_table(
        "acquisition_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("outcome", sa.String(16), nullable=False),
    )
    op.create_index("ix_acquisition_attempts_product_id", "acquisition_attempts", ["product_id"])
    op.create_index("ix_acquisition_attempts_started_at", "acquisition_attempts", ["started_at"])


def downgrade() -> None:
    op.drop_index("ix_acquisition_attempts_started_at", table_name="acquisition_attempts")
    op.drop_index("ix_acquisition_attempts_product_id", table_name="acquisition_attempts")
    op.drop_table("acquisition_attempts")
    op.drop_column("refresh_requests", "override_at")

"""Persist optional runtime monitoring intervals."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "runtime_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("poll_interval_seconds", sa.Integer()),
        sa.Column("failed_retry_seconds", sa.Integer()),
        sa.CheckConstraint("id = 1", name="runtime_settings_singleton"),
        sa.CheckConstraint(
            "poll_interval_seconds IS NULL OR poll_interval_seconds >= 60",
            name="runtime_settings_poll_interval_minimum",
        ),
        sa.CheckConstraint(
            "failed_retry_seconds IS NULL OR failed_retry_seconds >= 60",
            name="runtime_settings_failed_retry_minimum",
        ),
    )


def downgrade() -> None:
    op.drop_table("runtime_settings")

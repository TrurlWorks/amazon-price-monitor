"""Route all Amazon acquisition through a paced, persistent product queue."""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("products", sa.Column("pause_reason", sa.String(16), nullable=True))
    op.add_column(
        "refresh_requests",
        sa.Column("due_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.add_column(
        "refresh_requests",
        sa.Column("kind", sa.String(16), nullable=False, server_default="regular"),
    )
    op.add_column("refresh_requests", sa.Column("started_at", sa.DateTime(), nullable=True))
    op.create_table(
        "queue_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("last_started_at", sa.DateTime(), nullable=True),
        sa.Column("cooldown_until", sa.DateTime(), nullable=True),
        sa.Column("challenge_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("manual_streak", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_challenge_product_id", sa.Integer(), nullable=True),
        sa.Column("last_challenge_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("id = 1", name="queue_state_singleton"),
    )
    connection = op.get_bind()
    connection.execute(sa.text("INSERT INTO queue_state (id) VALUES (1)"))
    connection.execute(sa.text("""
        UPDATE products SET pause_reason = CASE
            WHEN automatic_failures >= 3 THEN 'automatic' ELSE 'manual' END
        WHERE is_active = 0
    """))
    connection.execute(sa.text("""
        DELETE FROM refresh_requests WHERE product_id IN (
            SELECT id FROM products WHERE pause_reason = 'manual'
        )
    """))
    connection.execute(sa.text("""
        UPDATE refresh_requests SET
            due_at = CASE WHEN product_id IN (
                SELECT id FROM products WHERE pause_reason = 'automatic'
            ) THEN datetime('now', '+12 hours') ELSE CURRENT_TIMESTAMP END,
            kind = CASE WHEN product_id IN (
                SELECT id FROM products WHERE pause_reason = 'automatic'
            ) THEN 'recovery' WHEN product_id IN (
                SELECT id FROM products WHERE consecutive_failures > 0
            ) THEN 'retry' ELSE 'regular' END
    """))
    connection.execute(sa.text("""
        INSERT INTO refresh_requests (product_id, requested_at, due_at, kind)
        SELECT id, CURRENT_TIMESTAMP,
            CASE WHEN pause_reason = 'automatic'
                THEN datetime('now', '+12 hours') ELSE CURRENT_TIMESTAMP END,
            CASE WHEN pause_reason = 'automatic' THEN 'recovery'
                 WHEN consecutive_failures > 0 THEN 'retry'
                 ELSE 'regular' END
        FROM products
        WHERE (is_active = 1 OR pause_reason = 'automatic')
          AND id NOT IN (SELECT product_id FROM refresh_requests)
    """))


def downgrade() -> None:
    op.drop_table("queue_state")
    op.drop_column("refresh_requests", "started_at")
    op.drop_column("refresh_requests", "kind")
    op.drop_column("refresh_requests", "due_at")
    op.drop_column("products", "pause_reason")

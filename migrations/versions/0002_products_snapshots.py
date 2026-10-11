"""P2 products and append-only price history (SQLite)."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asin", sa.String(10), nullable=False, unique=True),
        sa.Column("amazon_url", sa.String(), nullable=False),
        sa.Column("title", sa.String()),
        sa.Column("image_url", sa.String()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_checked_at", sa.DateTime()),
        sa.Column(
            "status",
            sa.Enum(
                "ACTIVE", "UNAVAILABLE", "NOT_FOUND", "UNKNOWN",
                native_enum=False, create_constraint=True, name="product_status",
            ),
            nullable=False, server_default="UNKNOWN",
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("consecutive_not_found", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint(
            "consecutive_failures >= 0 AND consecutive_not_found >= 0",
            name="product_nonnegative_counters",
        ),
        sa.CheckConstraint(
            "length(asin) = 10 AND asin NOT GLOB '*[^A-Z0-9]*'",
            name="product_asin_format",
        ),
        sa.CheckConstraint(
            "amazon_url = 'https://www.amazon.pl/dp/' || asin",
            name="product_canonical_url",
        ),
    )
    op.create_table(
        "price_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "product_id", sa.Integer(),
            sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("price", sa.Numeric(12, 2)),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("seller", sa.String()),
        sa.Column("availability", sa.String()),
        sa.Column("is_buy_box", sa.Boolean()),
        sa.Column("checked_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "price IS NULL OR (price >= 0 AND price <= 9999999999.99)",
            name="snapshot_price_range",
        ),
        sa.CheckConstraint(
            "length(currency) = 3 AND currency NOT GLOB '*[^A-Z]*'",
            name="snapshot_currency_format",
        ),
    )
    op.create_index("ix_price_snapshots_product_id", "price_snapshots", ["product_id"])
    op.create_index("ix_price_snapshots_checked_at", "price_snapshots", ["checked_at"])
    op.execute("""
        CREATE TRIGGER price_snapshots_no_update BEFORE UPDATE ON price_snapshots
        BEGIN SELECT RAISE(ABORT, 'Price snapshots are immutable'); END
    """)
    op.execute("""
        CREATE TRIGGER price_snapshots_no_delete BEFORE DELETE ON price_snapshots
        WHEN EXISTS (SELECT 1 FROM products WHERE id = OLD.product_id)
        BEGIN SELECT RAISE(ABORT, 'Delete the product explicitly instead'); END
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER price_snapshots_no_delete")
    op.execute("DROP TRIGGER price_snapshots_no_update")
    op.drop_table("price_snapshots")
    op.drop_table("products")

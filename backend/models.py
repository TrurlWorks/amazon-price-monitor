"""Domain persistence models. Schema and immutability guards are owned by Alembic."""

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import Boolean, CheckConstraint, DateTime, Enum, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class ProductStatus(StrEnum):
    ACTIVE = "ACTIVE"
    UNAVAILABLE = "UNAVAILABLE"
    NOT_FOUND = "NOT_FOUND"
    UNKNOWN = "UNKNOWN"


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint(
            "consecutive_failures >= 0 AND consecutive_not_found >= 0",
            name="product_nonnegative_counters",
        ),
        CheckConstraint(
            "length(asin) = 10 AND asin NOT GLOB '*[^A-Z0-9]*'",
            name="product_asin_format",
        ),
        CheckConstraint(
            "amazon_url = 'https://www.amazon.pl/dp/' || asin",
            name="product_canonical_url",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    asin: Mapped[str] = mapped_column(String(10), unique=True)
    amazon_url: Mapped[str] = mapped_column(String)
    title: Mapped[str | None] = mapped_column(String)
    image_url: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[ProductStatus] = mapped_column(
        Enum(
            ProductStatus, native_enum=False, create_constraint=True,
            name="product_status",
        ),
        default=ProductStatus.UNKNOWN,
        server_default="UNKNOWN",
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    pause_reason: Mapped[str | None] = mapped_column(String(16))
    consecutive_failures: Mapped[int] = mapped_column(default=0, server_default="0")
    automatic_failures: Mapped[int] = mapped_column(default=0, server_default="0")
    consecutive_not_found: Mapped[int] = mapped_column(default=0, server_default="0")
    refresh_request: Mapped["RefreshRequest | None"] = relationship(
        back_populates="product", uselist=False, passive_deletes=True,
    )

    @property
    def next_check_at(self) -> datetime | None:
        return self.refresh_request.due_at if self.refresh_request else None

    @property
    def queue_state(self) -> str | None:
        request = self.refresh_request
        if request is None:
            return None
        return "checking" if request.started_at else request.kind


class RefreshRequest(Base):
    """One durable, coalesced acquisition slot per product."""

    __tablename__ = "refresh_requests"

    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), primary_key=True,
    )
    requested_at: Mapped[datetime] = mapped_column(DateTime)
    due_at: Mapped[datetime] = mapped_column(DateTime)
    kind: Mapped[str] = mapped_column(String(16), default="regular")
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    override_at: Mapped[datetime | None] = mapped_column(DateTime)
    product: Mapped[Product] = relationship(back_populates="refresh_request")


class AcquisitionAttempt(Base):
    """Outcome of one worker acquisition, including interrupted claims."""

    __tablename__ = "acquisition_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), index=True,
    )
    kind: Mapped[str] = mapped_column(String(16))
    started_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    outcome: Mapped[str] = mapped_column(String(16))


class QueueState(Base):
    __tablename__ = "queue_state"
    __table_args__ = (CheckConstraint("id = 1", name="queue_state_singleton"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    last_started_at: Mapped[datetime | None] = mapped_column(DateTime)
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime)
    challenge_count: Mapped[int] = mapped_column(default=0, server_default="0")
    manual_streak: Mapped[int] = mapped_column(default=0, server_default="0")
    last_challenge_product_id: Mapped[int | None] = mapped_column()
    last_challenge_at: Mapped[datetime | None] = mapped_column(DateTime)


class PriceSnapshot(Base):
    __tablename__ = "price_snapshots"
    __table_args__ = (
        CheckConstraint(
            "price IS NULL OR (price >= 0 AND price <= 9999999999.99)",
            name="snapshot_price_range",
        ),
        CheckConstraint(
            "length(currency) = 3 AND currency NOT GLOB '*[^A-Z]*'",
            name="snapshot_currency_format",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), index=True,
    )
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3))
    seller: Mapped[str | None] = mapped_column(String)
    availability: Mapped[str | None] = mapped_column(String)
    is_buy_box: Mapped[bool | None] = mapped_column(Boolean)
    checked_at: Mapped[datetime] = mapped_column(DateTime, index=True)


class RuntimeSettings(Base):
    __tablename__ = "runtime_settings"
    __table_args__ = (
        CheckConstraint("id = 1", name="runtime_settings_singleton"),
        CheckConstraint(
            "poll_interval_seconds IS NULL OR poll_interval_seconds >= 60",
            name="runtime_settings_poll_interval_minimum",
        ),
        CheckConstraint(
            "failed_retry_seconds IS NULL OR failed_retry_seconds >= 60",
            name="runtime_settings_failed_retry_minimum",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    poll_interval_seconds: Mapped[int | None]
    failed_retry_seconds: Mapped[int | None]
    display_mode: Mapped[str] = mapped_column(String, default="tiles", server_default="tiles")


def naive_utc(value: datetime) -> datetime:
    """SQLite stores UTC without an offset; reject ambiguous naive input."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("An aware timestamp is required")
    return value.astimezone(UTC).replace(tzinfo=None)

"""Repositories flush only; callers own commit/rollback and transaction boundaries."""

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, localcontext
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.amazon_urls import normalize_asin
from backend.models import (
    PriceSnapshot,
    Product,
    RuntimeSettings,
    naive_utc,
    utcnow,
)


def database_counts(session: Session) -> tuple[int, int]:
    """Read both totals in one statement, including inactive products."""
    products, snapshots = session.execute(
        select(
            select(func.count()).select_from(Product).scalar_subquery(),
            select(func.count()).select_from(PriceSnapshot).scalar_subquery(),
        )
    ).one()
    return products, snapshots


@dataclass(frozen=True)
class EffectiveIntervals:
    poll_interval_seconds: int
    failed_retry_seconds: int


def effective_intervals(session: Session, settings) -> EffectiveIntervals:
    runtime = session.get(RuntimeSettings, 1)
    return EffectiveIntervals(
        poll_interval_seconds=(
            runtime.poll_interval_seconds
            if runtime is not None and runtime.poll_interval_seconds is not None
            else settings.poll_interval_seconds
        ),
        failed_retry_seconds=(
            runtime.failed_retry_seconds
            if runtime is not None and runtime.failed_retry_seconds is not None
            else settings.failed_retry_seconds
        ),
    )


def display_mode(session: Session) -> str:
    runtime = session.get(RuntimeSettings, 1)
    return runtime.display_mode if runtime is not None else "tiles"


def set_runtime_intervals(
    session: Session, *, poll_interval_seconds: int, failed_retry_seconds: int,
    display_mode: str | None = None,
) -> RuntimeSettings:
    runtime = session.get(RuntimeSettings, 1)
    if runtime is None:
        runtime = RuntimeSettings(id=1)
        session.add(runtime)
    runtime.poll_interval_seconds = poll_interval_seconds
    runtime.failed_retry_seconds = failed_retry_seconds
    if display_mode is not None:
        runtime.display_mode = display_mode
    session.flush()
    return runtime


@dataclass(frozen=True)
class PriceStats:
    current: Decimal | None = None
    initial: Decimal | None = None
    change_amount: Decimal | None = None
    change_percent: Decimal | None = None
    minimum: Decimal | None = None
    maximum: Decimal | None = None
    average: Decimal | None = None
    minimum_at: datetime | None = None
    maximum_at: datetime | None = None


class ProductRepository(Protocol):
    def add(
        self, asin: str, *, title: str | None = None, image_url: str | None = None,
    ) -> Product: ...
    def get(self, product_id: int) -> Product | None: ...
    def get_by_asin(self, asin: str) -> Product | None: ...
    def list(self) -> list[Product]: ...
    def set_active(self, product_id: int, active: bool) -> None: ...
    def delete(self, product_id: int) -> None: ...


class SnapshotRepository(Protocol):
    def append(
        self, product_id: int, *, price: Decimal | None, currency: str,
        checked_at: datetime, seller: str | None = None,
        availability: str | None = None, is_buy_box: bool | None = None,
    ) -> PriceSnapshot: ...
    def history(self, product_id: int, currency: str) -> list[PriceSnapshot]: ...
    def stats(self, product_id: int, currency: str) -> PriceStats: ...


def normalize_currency(currency: str) -> str:
    value = currency.strip().upper()
    if re.fullmatch(r"[A-Z]{3}", value) is None:
        raise ValueError("Currency must contain three ASCII letters")
    return value


class SQLAlchemyProductRepository:
    def __init__(self, session: Session):
        self.session = session

    def add(
        self, asin: str, *, title: str | None = None, image_url: str | None = None,
    ) -> Product:
        asin = normalize_asin(asin)
        now = naive_utc(utcnow())
        product = Product(
            asin=asin, amazon_url=f"https://www.amazon.pl/dp/{asin}",
            title=title, image_url=image_url, created_at=now, first_seen_at=now,
        )
        self.session.add(product)
        self.session.flush()
        return product

    def get(self, product_id: int) -> Product | None:
        return self.session.get(Product, product_id)

    def get_by_asin(self, asin: str) -> Product | None:
        return self.session.scalar(select(Product).where(Product.asin == normalize_asin(asin)))

    def list(self) -> list[Product]:
        return list(self.session.scalars(select(Product).order_by(Product.id)))

    def set_active(self, product_id: int, active: bool) -> None:
        product = self.get(product_id)
        if product is None:
            raise LookupError(product_id)
        product.is_active = active
        self.session.flush()

    def delete(self, product_id: int) -> None:
        product = self.get(product_id)
        if product is not None:
            self.session.delete(product)
            self.session.flush()
            self.session.expire_all()


class SQLAlchemySnapshotRepository:
    def __init__(self, session: Session):
        self.session = session

    def append(
        self, product_id: int, *, price: Decimal | None, currency: str,
        checked_at: datetime, seller: str | None = None,
        availability: str | None = None, is_buy_box: bool | None = None,
    ) -> PriceSnapshot:
        if price is not None:
            if not isinstance(price, Decimal) or not price.is_finite():
                raise ValueError("Price must be a finite Decimal or None")
            if not Decimal(0) <= price <= Decimal("9999999999.99"):
                raise ValueError("Price is outside Numeric(12, 2) range")
            with localcontext() as context:
                context.prec = 28
                if price != price.quantize(Decimal("0.01")):
                    raise ValueError("Price must have at most two fractional digits")
        snapshot = PriceSnapshot(
            product_id=product_id, price=price, currency=normalize_currency(currency),
            checked_at=naive_utc(checked_at), seller=seller,
            availability=availability, is_buy_box=is_buy_box,
        )
        self.session.add(snapshot)
        self.session.flush()
        return snapshot

    def history(self, product_id: int, currency: str) -> list[PriceSnapshot]:
        return list(self.session.scalars(
            select(PriceSnapshot).where(
                PriceSnapshot.product_id == product_id,
                PriceSnapshot.currency == normalize_currency(currency),
            ).order_by(PriceSnapshot.checked_at, PriceSnapshot.id)
        ))

    def stats(self, product_id: int, currency: str) -> PriceStats:
        return calculate_stats(self.history(product_id, currency))


def calculate_stats(snapshots: list[PriceSnapshot]) -> PriceStats:
    """Chronological endpoints include missing prices; aggregates exclude them."""
    if not snapshots:
        return PriceStats()
    if len({snapshot.currency for snapshot in snapshots}) != 1:
        raise ValueError("Statistics require one currency")
    ordered = sorted(snapshots, key=lambda snapshot: (snapshot.checked_at, snapshot.id))
    initial, current = ordered[0].price, ordered[-1].price
    priced = [snapshot for snapshot in ordered if snapshot.price is not None]
    with localcontext() as context:
        context.prec = 28
        change = None if initial is None or current is None else current - initial
        percent = None if change is None or initial == 0 else change / initial * 100
        if not priced:
            return PriceStats(current=current, initial=initial)
        minimum = min(priced, key=lambda snapshot: snapshot.price)
        maximum = max(priced, key=lambda snapshot: snapshot.price)
        average = sum((snapshot.price for snapshot in priced), Decimal(0)) / len(priced)
        return PriceStats(
            current=current,
            initial=initial,
            change_amount=change,
            change_percent=percent,
            minimum=minimum.price,
            maximum=maximum.price,
            average=average,
            minimum_at=minimum.checked_at,
            maximum_at=maximum.checked_at,
        )

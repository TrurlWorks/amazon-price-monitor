"""Acquisition and transaction policy, independent of HTTP."""

from httpx import RequestError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.amazon_page_provider import AmazonPageProvider
from backend.amazon_urls import parse_amazon_url
from backend.acquisition_queue import begin_direct, enqueue, finish, remove
from backend.config import Settings
from backend.mock_provider import MockAmazonProvider
from backend.models import PriceSnapshot, Product, ProductStatus, naive_utc, utcnow
from backend.providers import (
    AmazonBlocked,
    Availability,
    OfferData,
    ProductNotFound,
    ProductProvider,
    ProviderError,
    ProviderUnavailable,
    TransientProviderError,
)
from backend.repositories import (
    SQLAlchemyProductRepository,
    SQLAlchemySnapshotRepository,
    normalize_currency,
)


class MissingProduct(Exception):
    pass


class DuplicateProduct(Exception):
    pass


class InvalidCurrency(ValueError):
    pass


class RefreshInProgress(Exception):
    pass


class ProductService:
    def __init__(
        self, session: Session, provider: ProductProvider, settings: Settings | None = None,
    ):
        self.session = session
        self.provider = provider
        self.settings = settings if settings is not None else Settings()
        self.products = SQLAlchemyProductRepository(session)
        self.snapshots = SQLAlchemySnapshotRepository(session)

    def list(self):
        return self.products.list()

    def get(self, product_id: int) -> Product:
        product = self.products.get(product_id)
        if product is None:
            raise MissingProduct()
        return product

    async def _get_offer(self, asin: str) -> OfferData:
        # Preserve custom acquisition behavior supplied by provider subclasses.
        if type(self.provider) is MockAmazonProvider:
            observation = self.session.scalar(
                select(func.count())
                .select_from(PriceSnapshot)
                .join(Product, PriceSnapshot.product_id == Product.id)
                .where(Product.asin == asin)
            )
            return self.provider.offer_at(asin, observation)
        return await self.provider.get_offer(asin)

    def add_queued(self, url: str) -> Product:
        """Persist a placeholder and its first check without contacting Amazon."""
        parsed = parse_amazon_url(url)
        if self.products.get_by_asin(parsed.asin) is not None:
            raise DuplicateProduct()
        try:
            product = self.products.add(parsed.asin)
            enqueue(
                self.session, product, kind="manual", due_at=naive_utc(utcnow()),
            )
            self.session.commit()
            return product
        except IntegrityError:
            self.session.rollback()
            if self.products.get_by_asin(parsed.asin) is not None:
                raise DuplicateProduct() from None
            raise
        except Exception:
            self.session.rollback()
            raise

    def queue_refresh(self, product_id: int) -> Product:
        product = self.get(product_id)
        try:
            enqueue(
                self.session, product, kind="manual", due_at=naive_utc(utcnow()),
            )
            self.session.commit()
            return product
        except Exception:
            self.session.rollback()
            raise

    async def refresh_now(self, product_id: int) -> Product:
        """Perform one immediate read; keep the queued schedule on failure."""
        self.get(product_id)
        if not begin_direct(self.session, product_id, naive_utc(utcnow())):
            raise RefreshInProgress()
        succeeded = False
        blocked = False
        outcome = "error"
        try:
            product = await self.refresh(product_id)
            succeeded = True
            outcome = "success"
            return product
        except ProviderError as error:
            blocked = isinstance(error, AmazonBlocked)
            outcome = "blocked" if blocked else "not_found" if isinstance(error, ProductNotFound) else "error"
            raise
        finally:
            finish(
                self.session, self.settings, product_id, "manual", naive_utc(utcnow()),
                succeeded=succeeded, blocked=blocked, outcome=outcome, direct=True,
            )

    def record(self, product: Product, offer: OfferData) -> None:
        if offer.asin != product.asin:
            raise ProviderUnavailable("Provider returned a different ASIN")
        try:
            self.snapshots.append(
                product.id, price=offer.price, currency=offer.currency,
                checked_at=offer.checked_at, seller=offer.seller,
                availability=offer.availability, is_buy_box=offer.is_buy_box,
            )
        except ValueError as exc:
            raise ProviderUnavailable("Invalid provider observation") from exc
        product.status = ProductStatus.UNKNOWN
        if offer.availability == Availability.AVAILABLE:
            product.status = ProductStatus.ACTIVE
        elif offer.availability == Availability.UNAVAILABLE:
            # Insertion order represents acquisition order, even when provider
            # timestamps repeat or move backwards. Include every currency.
            recent = list(self.session.scalars(
                select(PriceSnapshot.availability)
                .where(PriceSnapshot.product_id == product.id)
                .order_by(PriceSnapshot.id.desc())
                .limit(self.settings.unavailable_threshold)
            ))
            if (
                len(recent) == self.settings.unavailable_threshold
                and all(value == Availability.UNAVAILABLE for value in recent)
            ):
                product.status = ProductStatus.UNAVAILABLE
        product.last_checked_at = naive_utc(utcnow())
        product.consecutive_failures = 0
        if product.is_active or product.automatic_failures < 3:
            product.automatic_failures = 0
        product.consecutive_not_found = 0

    async def refresh(self, product_id: int, *, automated: bool = False) -> Product:
        product = self.get(product_id)
        if automated and not product.is_active and product.pause_reason != "automatic":
            return product
        asin = product.asin
        self.session.rollback()
        try:
            try:
                metadata = await self.provider.get_product(asin)
                offer = await self._get_offer(asin)
            except (RequestError, OSError) as exc:
                raise TransientProviderError("Provider request failed") from exc
            product = self.get(product_id)
            if automated and not product.is_active and product.pause_reason != "automatic":
                return product
            if metadata.asin != asin:
                raise ProviderUnavailable("Provider returned a different ASIN")
            if product.pause_reason == "automatic":
                product.is_active = True
                product.pause_reason = None
                product.automatic_failures = 0
            self.record(product, offer)
            product.title = metadata.title
            product.image_url = metadata.image_url
            self.session.commit()
            return product
        except ProviderError as exc:
            self.session.rollback()
            product = self.get(product_id)
            product.last_checked_at = naive_utc(utcnow())
            product.consecutive_failures += 1
            if automated:
                product.automatic_failures += 1
                if product.automatic_failures >= 3:
                    product.automatic_failures = 3
                    product.is_active = False
                    product.pause_reason = "automatic"
            product.status = ProductStatus.UNKNOWN
            if isinstance(exc, ProductNotFound):
                product.consecutive_not_found += 1
                if product.consecutive_not_found >= self.settings.not_found_threshold:
                    product.status = ProductStatus.NOT_FOUND
            else:
                product.consecutive_not_found = 0
            # Failed acquisition is not an observation; preserve all snapshots.
            self.session.commit()
            raise
        except Exception:
            self.session.rollback()
            raise

    def set_active(self, product_id: int, is_active: bool) -> Product:
        product = self.get(product_id)
        try:
            self.products.set_active(product_id, is_active)
            if is_active:
                product.automatic_failures = 0
                product.pause_reason = None
                enqueue(
                    self.session, product, kind="manual", due_at=naive_utc(utcnow()),
                )
            else:
                product.automatic_failures = 0
                product.pause_reason = "manual"
                remove(self.session, product_id)
            self.session.commit()
            return product
        except Exception:
            self.session.rollback()
            raise

    def delete(self, product_id: int) -> None:
        self.get(product_id)
        try:
            self.products.delete(product_id)
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

    def history(self, product_id: int, currency: str):
        self.get(product_id)
        try:
            currency = normalize_currency(currency)
        except ValueError as exc:
            raise InvalidCurrency() from exc
        observations = self.snapshots.history(product_id, currency)
        return {
            "product_id": product_id,
            "currency": currency,
            "snapshots": observations,
            "stats": self.snapshots.stats(product_id, currency),
        }


def create_provider(settings):
    if settings.product_provider == "amazon_page":
        return AmazonPageProvider()
    return MockAmazonProvider(settings.mock_scenario)

"""Acquisition contracts only; P3 contains no network implementation."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from backend.amazon_urls import AmazonProductURL, normalize_asin


class Availability(StrEnum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ProductData:
    asin: str
    title: str | None = None
    image_url: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "asin", normalize_asin(self.asin))

    @property
    def amazon_url(self) -> str:
        return AmazonProductURL(self.asin).canonical_url


@dataclass(frozen=True)
class OfferData:
    asin: str
    price: Decimal | None
    currency: str
    checked_at: datetime
    availability: Availability = Availability.UNKNOWN
    seller: str | None = None
    is_buy_box: bool | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "asin", normalize_asin(self.asin))
        if self.checked_at.tzinfo is None or self.checked_at.utcoffset() is None:
            raise ValueError("An aware observation timestamp is required")
        if self.price is not None:
            if not isinstance(self.price, Decimal) or not self.price.is_finite():
                raise ValueError("Price must be a finite Decimal or None")
            if self.price < 0:
                raise ValueError("Price cannot be negative")


class ProviderError(Exception):
    """Base for acquisition failures; never itself evidence of absence."""


class ProductNotFound(ProviderError):
    """Provider positively confirmed the product does not exist."""


class ProviderUnavailable(ProviderError):
    """Provider cannot serve requests, e.g. missing credentials or access."""


class TransientProviderError(ProviderError):
    """Temporary failure, e.g. timeout, throttling, CAPTCHA or upstream error."""


class AmazonBlocked(TransientProviderError):
    """A recognizable Amazon verification page; pause shared acquisition."""


class ProductProvider(Protocol):
    """Receive normalized ASINs, never user URLs; failures raise ProviderError.

    No offer means UNAVAILABLE, not ProductNotFound. Unknown data stays unknown.
    """

    async def get_product(self, asin: str) -> ProductData: ...
    async def get_offer(self, asin: str) -> OfferData: ...

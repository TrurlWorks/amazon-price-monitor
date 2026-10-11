import inspect
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from decimal import Decimal
from typing import get_type_hints
from unittest import IsolatedAsyncioTestCase, TestCase

from backend.providers import (
    Availability,
    OfferData,
    ProductData,
    ProductNotFound,
    ProductProvider,
    ProviderError,
    ProviderUnavailable,
    TransientProviderError,
)

ASIN = "B012345678"
CHECKED_AT = datetime(2026, 1, 1, tzinfo=UTC)


class FakeProvider:
    def __init__(self, error: ProviderError | None = None):
        self.error = error
        self.calls: list[str] = []

    async def get_product(self, asin: str) -> ProductData:
        self.calls.append(asin)
        if self.error is not None:
            raise self.error
        return ProductData(asin, title="Example")

    async def get_offer(self, asin: str) -> OfferData:
        self.calls.append(asin)
        if self.error is not None:
            raise self.error
        return OfferData(
            asin, None, "PLN", CHECKED_AT, availability=Availability.UNAVAILABLE,
        )


class ProviderContractTests(IsolatedAsyncioTestCase):
    async def test_structural_provider_and_unavailable_offer(self):
        fake = FakeProvider()
        provider: ProductProvider = fake
        product = await provider.get_product(ASIN)
        offer = await provider.get_offer(ASIN)
        self.assertEqual(fake.calls, [ASIN, ASIN])
        self.assertEqual(product.asin, ASIN)
        self.assertEqual(product.title, "Example")
        self.assertEqual(product.amazon_url, f"https://www.amazon.pl/dp/{ASIN}")
        self.assertIsNone(offer.price)
        self.assertEqual(offer.availability, Availability.UNAVAILABLE)
        self.assertEqual(offer.checked_at, CHECKED_AT)

    async def test_failures_remain_distinct_for_both_operations(self):
        for failure in (ProductNotFound, ProviderUnavailable, TransientProviderError):
            error = failure("fixture failure")
            provider: ProductProvider = FakeProvider(error)
            for operation in (provider.get_product, provider.get_offer):
                with self.subTest(failure=failure, operation=operation):
                    with self.assertRaises(failure) as caught:
                        await operation(ASIN)
                    self.assertIs(caught.exception, error)
                    self.assertIsInstance(error, ProviderError)
                    self.assertEqual(isinstance(error, ProductNotFound), failure is ProductNotFound)


class ProviderDataTests(TestCase):
    def test_protocol_declares_async_typed_operations(self):
        for name, result in (("get_product", ProductData), ("get_offer", OfferData)):
            method = getattr(ProductProvider, name)
            self.assertTrue(inspect.iscoroutinefunction(method))
            self.assertEqual(get_type_hints(method), {"asin": str, "return": result})

    def test_normalized_immutable_data_and_exact_decimal(self):
        product = ProductData(ASIN.lower())
        offer = OfferData(ASIN.lower(), Decimal("0.10"), "PLN", CHECKED_AT)
        self.assertEqual(product.asin, ASIN)
        self.assertEqual(offer.asin, ASIN)
        self.assertEqual(offer.price, Decimal("0.10"))
        self.assertEqual(offer.availability, Availability.UNKNOWN)
        self.assertIsNone(offer.is_buy_box)
        with self.assertRaises(FrozenInstanceError):
            product.title = "Changed"
        with self.assertRaises(FrozenInstanceError):
            offer.price = Decimal("1")

    def test_invalid_data_is_rejected(self):
        for price in (0.1, Decimal("NaN"), Decimal("Infinity"), Decimal("-1")):
            with self.subTest(price=price), self.assertRaises(ValueError):
                OfferData(ASIN, price, "PLN", CHECKED_AT)
        with self.assertRaises(ValueError):
            OfferData(ASIN, None, "PLN", CHECKED_AT.replace(tzinfo=None))
        for asin in ("invalid", "B01234567ſ", "B0123456ß"):
            with self.subTest(asin=asin):
                with self.assertRaises(ValueError):
                    ProductData(asin)
                with self.assertRaises(ValueError):
                    OfferData(asin, None, "PLN", CHECKED_AT)

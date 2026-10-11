"""Offline fixtures, deterministic for ASIN, scenario and per-instance observation."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from backend.amazon_urls import normalize_asin
from backend.providers import Availability, OfferData, ProductData

SCENARIOS = frozenset({"stable", "decreasing", "increasing", "temporary", "recovered"})
EPOCH = datetime(2026, 1, 1, tzinfo=UTC)


class MockAmazonProvider:
    def __init__(self, scenario: str = "stable"):
        if scenario not in SCENARIOS:
            raise ValueError("Unsupported mock scenario")
        self.scenario = scenario
        self.observations: dict[str, int] = {}

    async def get_product(self, asin: str) -> ProductData:
        asin = normalize_asin(asin)
        return ProductData(asin, title=f"Mock Amazon.pl product {asin}")

    async def get_offer(self, asin: str) -> OfferData:
        asin = normalize_asin(asin)
        count = self.observations.get(asin, 0)
        offer = self.offer_at(asin, count)
        self.observations[asin] = count + 1
        return offer

    def offer_at(self, asin: str, observation: int) -> OfferData:
        """Zero-based observation; pure and usable for persisted replay."""
        asin = normalize_asin(asin)
        if observation < 0:
            raise ValueError("Observation must be nonnegative")
        base = Decimal(10000 + sum((i + 1) * ord(c) for i, c in enumerate(asin))) / 100
        delta = Decimal(min(observation, 10000)) / 100
        price = base
        if self.scenario == "decreasing":
            price = max(Decimal("0"), base - delta)
        elif self.scenario == "increasing":
            price = base + delta
        unavailable = (
            self.scenario == "temporary" and observation in (1, 2)
        ) or (
            self.scenario == "recovered" and observation < 2
        )
        return OfferData(
            asin=asin,
            price=None if unavailable else price,
            currency="PLN",
            checked_at=EPOCH + timedelta(seconds=observation),
            availability=Availability.UNAVAILABLE if unavailable else Availability.AVAILABLE,
            seller=None if unavailable else "Mock seller",
            is_buy_box=False if unavailable else True,
        )

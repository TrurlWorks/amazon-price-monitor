from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from pydantic import ValidationError

from backend.config import Settings
from backend.mock_provider import SCENARIOS, MockAmazonProvider
from backend.providers import Availability

ASIN = "B012345678"


class MockProviderTests(IsolatedAsyncioTestCase):
    async def test_deterministic_offline_scenarios(self):
        for scenario in SCENARIOS:
            with self.subTest(scenario=scenario):
                first = MockAmazonProvider(scenario)
                second = MockAmazonProvider(scenario)
                with patch("socket.getaddrinfo", side_effect=AssertionError("Network forbidden")):
                    self.assertEqual(
                        await first.get_product(ASIN), await second.get_product(ASIN),
                    )
                    offers = [await first.get_offer(ASIN) for _ in range(5)]
                    self.assertEqual(offers, [await second.get_offer(ASIN) for _ in range(5)])
                self.assertEqual(first.observations[ASIN], 5)
                self.assertEqual(await first.get_offer("0123456789"),
                                 second.offer_at("0123456789", 0))
                prices = [offer.price for offer in offers]
                if scenario == "stable":
                    self.assertEqual(len(set(prices)), 1)
                elif scenario == "increasing":
                    self.assertTrue(all(a < b for a, b in zip(prices, prices[1:])))
                elif scenario == "decreasing":
                    self.assertTrue(all(a > b for a, b in zip(prices, prices[1:])))
                else:
                    missing = [i for i, price in enumerate(prices) if price is None]
                    self.assertEqual(missing, [1, 2] if scenario == "temporary" else [0, 1])
                    self.assertEqual(offers[-1].availability, Availability.AVAILABLE)

    async def test_validation_and_metadata_do_not_consume_observations(self):
        provider = MockAmazonProvider()
        await provider.get_product(ASIN.lower())
        self.assertEqual(provider.observations, {})
        self.assertEqual(await provider.get_offer(ASIN.lower()), provider.offer_at(ASIN, 0))
        with self.assertRaises(ValueError):
            MockAmazonProvider("network")
        with self.assertRaises(ValueError):
            await provider.get_offer("invalid")

    def test_configuration(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(Settings().product_provider, "mock")
        with patch.dict("os.environ", {"PRODUCT_PROVIDER": "real"}):
            with self.assertRaises(ValidationError):
                Settings()
        with patch.dict("os.environ", {"MONITOR_MOCK_SCENARIO": "recovered"}):
            self.assertEqual(Settings().mock_scenario, "recovered")

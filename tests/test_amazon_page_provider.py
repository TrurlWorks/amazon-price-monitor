from decimal import Decimal
from pathlib import Path
from unittest import IsolatedAsyncioTestCase

import httpx

from backend.amazon_page_provider import AmazonPageProvider, parse_page, parse_pln
from backend.config import Settings
from backend.providers import Availability, ProductNotFound, TransientProviderError
from backend.services import create_provider

ASIN = "B012345678"
FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / f"amazon_{name}.html").read_text(encoding="utf-8")


class AmazonPageTests(IsolatedAsyncioTestCase):
    async def test_extract_and_consume_one_page_per_observation(self):
        requests = []

        def respond(request):
            requests.append(request)
            self.assertEqual(str(request.url), f"https://www.amazon.pl/dp/{ASIN}")
            self.assertEqual(request.method, "GET")
            return httpx.Response(200, text=fixture("product"))

        provider = AmazonPageProvider(transport=httpx.MockTransport(respond))
        for count in (1, 2):
            product = await provider.get_product(ASIN.lower())
            offer = await provider.get_offer(ASIN)
            self.assertEqual(len(requests), count)
            self.assertEqual(product.title, "Prawdziwy produkt & akcesoria")
            self.assertEqual(product.image_url, "https://m.media-amazon.com/images/I/main.jpg")
            self.assertEqual(offer.price, Decimal("1234.56"))
            self.assertEqual(offer.currency, "PLN")
            self.assertEqual(offer.availability, Availability.AVAILABLE)
            self.assertEqual(offer.seller, "Sprzedawca testowy")
            self.assertIsNotNone(offer.checked_at.utcoffset())
        await provider.get_offer(ASIN)
        self.assertEqual(len(requests), 3)
        with self.assertRaises(ValueError):
            await provider.get_product("https://evil.test")
        self.assertEqual(len(requests), 3)

    async def test_missing_price_and_unavailable(self):
        for html, availability in (
            (fixture("unavailable"), Availability.UNAVAILABLE),
            ('<span id="productTitle">Produkt</span>', Availability.UNKNOWN),
        ):
            product, offer = parse_page(ASIN, html)
            self.assertTrue(product.title)
            self.assertIsNone(product.image_url)
            self.assertIsNone(offer.price)
            self.assertIsNone(offer.seller)
            self.assertEqual(offer.availability, availability)

    async def test_exact_polish_prices(self):
        for value in ("1 234,56 zł", "1\u202f234,56 PLN", "1.234,56 zł"):
            self.assertEqual(parse_pln(value), Decimal("1234.56"))
        self.assertEqual(parse_pln("0,10 zł"), Decimal("0.10"))
        for value in ("12.34 zł", "1,234 zł", "12,34 EUR", "NaN", "-1,00 zł"):
            with self.subTest(value=value), self.assertRaises(TransientProviderError):
                parse_pln(value)

    async def test_errors_redirects_and_captcha_never_become_observations(self):
        for status, html, error in (
            (200, fixture("captcha"), TransientProviderError),
            (404, fixture("captcha"), TransientProviderError),
            (403, "", TransientProviderError),
            (429, "", TransientProviderError),
            (500, "", TransientProviderError),
            (502, "", TransientProviderError),
            (503, "", TransientProviderError),
            (302, "", TransientProviderError),
            (200, "<html>Unexpected page</html>", TransientProviderError),
            (404, "<html>Not found</html>", ProductNotFound),
        ):
            calls = []

            def respond(request):
                calls.append(request)
                return httpx.Response(status, text=html, headers={"Location": "http://127.0.0.1"})

            provider = AmazonPageProvider(transport=httpx.MockTransport(respond))
            with self.subTest(status=status, html=html):
                with self.assertRaises(error):
                    await provider.get_product(ASIN)
                self.assertEqual(len(calls), 1)
                self.assertIsNone(provider._pending)

    async def test_network_failure_is_transient(self):
        def respond(request):
            raise httpx.ConnectError("fixture failure", request=request)

        provider = AmazonPageProvider(transport=httpx.MockTransport(respond))
        with self.assertRaises(TransientProviderError):
            await provider.get_offer(ASIN)

    async def test_provider_selection(self):
        self.assertIsInstance(
            create_provider(Settings(PRODUCT_PROVIDER="amazon_page")), AmazonPageProvider,
        )

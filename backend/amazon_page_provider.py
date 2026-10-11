"""Acquire one canonical server-rendered page per observation, without redirects."""

import re
from datetime import UTC, datetime
from decimal import Decimal
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup

from backend.amazon_urls import AmazonProductURL, normalize_asin
from backend.providers import (
    AmazonBlocked,
    Availability,
    OfferData,
    ProductData,
    ProductNotFound,
    TransientProviderError,
)

PRICE_SELECTORS = (
    "#corePriceDisplay_desktop_feature_div .priceToPay .a-offscreen",
    "#corePrice_feature_div .priceToPay .a-offscreen",
    "#corePriceDisplay_desktop_feature_div .a-price:not(.a-text-price) .a-offscreen",
    "#corePrice_feature_div .a-price:not(.a-text-price) .a-offscreen",
    "#apex_desktop .a-price:not(.a-text-price) .a-offscreen",
    "#priceblock_ourprice",
    "#priceblock_dealprice",
)


def parse_pln(value: str) -> Decimal:
    value = " ".join(value.split())
    match = re.fullmatch(
        r"([0-9]+|[0-9]{1,3}(?:[ .][0-9]{3})+),([0-9]{2})\s*(?:zł|PLN)",
        value,
    )
    if match is None:
        raise TransientProviderError("Unrecognized displayed PLN price")
    whole = match[1].replace(" ", "").replace(".", "")
    price = Decimal(f"{whole}.{match[2]}")
    if price > Decimal("9999999999.99"):
        raise TransientProviderError("Displayed price is outside the supported range")
    return price


def text_at(document, selector):
    node = document.select_one(selector)
    return " ".join(node.stripped_strings) if node else ""


def parse_page(asin: str, html: str) -> tuple[ProductData, OfferData]:
    document = BeautifulSoup(html, "html.parser")
    visible = document.get_text(" ", strip=True).casefold()
    if document.select_one(
        'form[action*="validateCaptcha"], #captchacharacters, input[name="amzn-r"]'
    ) or any(marker in visible for marker in (
        "robot check", "enter the characters you see below",
        "wpisz znaki widoczne", "sorry, we just need to make sure",
        "automated access to amazon", "api-services-support@amazon",
    )):
        raise AmazonBlocked("Amazon blocked the page request")
    title = text_at(document, "#productTitle")
    if not title:
        raise TransientProviderError("Unrecognized Amazon product page")
    image = document.select_one("#landingImage, #imgBlkFront")
    image_url = None
    if image:
        candidate = image.get("data-old-hires") or image.get("src") or ""
        try:
            parsed = urlsplit(candidate)
            if parsed.scheme == "https" and parsed.hostname and not parsed.username:
                image_url = candidate
        except ValueError:
            pass
    availability_text = text_at(document, "#availability").casefold()
    unavailable = any(marker in availability_text for marker in (
        "obecnie niedostęp", "tymczasowo niedostęp", "chwilowo niedostęp",
        "obecnie niedostep", "currently unavailable", "out of stock",
    ))
    price = None
    if not unavailable:
        for selector in PRICE_SELECTORS:
            displayed = text_at(document, selector)
            if displayed:
                price = parse_pln(displayed)
                break
    availability = Availability.UNKNOWN
    if unavailable:
        availability = Availability.UNAVAILABLE
    elif any(marker in availability_text for marker in (
        "dostępny", "dostępne", "w magazynie", "pozostało", "in stock",
    )):
        availability = Availability.AVAILABLE
    seller = text_at(document, "#sellerProfileTriggerId") or text_at(
        document, "#merchantInfoFeature_feature_div .offer-display-feature-text-message"
    )
    return (
        ProductData(asin, title=title, image_url=image_url),
        OfferData(
            asin, price, "PLN", datetime.now(UTC),
            availability=availability, seller=seller or None,
        ),
    )


class AmazonPageProvider:
    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None):
        self.transport = transport
        self._pending: tuple[ProductData, OfferData] | None = None

    async def _fetch(self, asin: str) -> tuple[ProductData, OfferData]:
        url = AmazonProductURL(asin).canonical_url
        try:
            async with httpx.AsyncClient(
                transport=self.transport, timeout=15, follow_redirects=False,
                trust_env=False, headers={"Accept-Language": "pl-PL,pl;q=0.9"},
            ) as client:
                response = await client.get(url)
        except httpx.RequestError as exc:
            raise TransientProviderError("Amazon page request failed") from exc
        if response.status_code == 404:
            # A challenge masquerading as a 404 is not confirmed absence.
            body = response.text.casefold()
            if any(marker in body for marker in (
                "captcha", "robot check", "automated access", "amzn-r",
            )):
                raise AmazonBlocked("Amazon blocked the page request")
            raise ProductNotFound("Amazon returned HTTP 404")
        if response.status_code != 200:
            raise TransientProviderError("Amazon page request was unsuccessful")
        return parse_page(asin, response.text)

    async def get_product(self, asin: str) -> ProductData:
        asin = normalize_asin(asin)
        # Always begin a fresh observation; do not retain stale pages on failure.
        self._pending = None
        self._pending = await self._fetch(asin)
        return self._pending[0]

    async def get_offer(self, asin: str) -> OfferData:
        asin = normalize_asin(asin)
        pending, self._pending = self._pending, None
        if pending is not None and pending[0].asin == asin:
            return pending[1]
        return (await self._fetch(asin))[1]

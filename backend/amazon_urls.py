"""Pure, allowlisted Amazon.pl URL parsing; never resolve or fetch input."""

import re
from dataclasses import dataclass

_URL = re.compile(
    r"(?i:https://(?:www\.)?amazon\.pl)"
    r"/(?:dp|gp/product)/(?P<asin>[A-Za-z0-9]{10})"
    r"(?:\?(?:[A-Za-z0-9._~!$&'()*+,;=:@/?-]|%[0-9A-Fa-f]{2})*)?"
)


class InvalidProductURL(ValueError):
    """Input is not an unambiguous supported product URL."""


def normalize_asin(asin: str) -> str:
    """Validate ASCII before uppercasing, which can expand Unicode letters."""
    if not isinstance(asin, str):
        raise ValueError("ASIN must be a string")
    value = asin.strip()
    if re.fullmatch(r"[A-Za-z0-9]{10}", value) is None:
        raise ValueError("ASIN must contain ten ASCII letters or digits")
    return value.upper()


@dataclass(frozen=True)
class AmazonProductURL:
    asin: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "asin", normalize_asin(self.asin))

    @property
    def canonical_url(self) -> str:
        return f"https://www.amazon.pl/dp/{self.asin}"


def parse_amazon_url(url: str) -> AmazonProductURL:
    """Accept exact product paths and a syntactically valid, ignored query."""
    if not isinstance(url, str):
        raise InvalidProductURL("Product URL must be a string")
    match = _URL.fullmatch(url)
    if match is None:
        raise InvalidProductURL("Unsupported or malformed Amazon.pl product URL")
    return AmazonProductURL(match["asin"])

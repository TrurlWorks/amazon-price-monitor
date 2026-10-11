from unittest import TestCase
from unittest.mock import patch

from backend.amazon_urls import InvalidProductURL, normalize_asin, parse_amazon_url
from backend.repositories import normalize_asin as repository_normalize_asin

ASIN = "B012345678"
CANONICAL = f"https://www.amazon.pl/dp/{ASIN}"


class AmazonURLTests(TestCase):
    def test_supported_urls_and_canonical_round_trip(self):
        for scheme in ("https", "HTTPS"):
            for host in ("amazon.pl", "www.amazon.pl", "AMAZON.PL", "WWW.AMAZON.PL"):
                for path in ("dp", "gp/product"):
                    for asin in (ASIN, ASIN.lower(), "0123456789", "abcdefghij"):
                        for query in ("", "?", "?tag=test-21&ref=abc", "?q=a%20b"):
                            url = f"{scheme}://{host}/{path}/{asin}{query}"
                            with self.subTest(url=url):
                                result = parse_amazon_url(url)
                                self.assertEqual(result.asin, asin.upper())
                                self.assertEqual(
                                    result.canonical_url,
                                    f"https://www.amazon.pl/dp/{asin.upper()}",
                                )
                                self.assertEqual(parse_amazon_url(result.canonical_url), result)

    def test_rejects_authority_and_scheme_attacks(self):
        authorities = (
            "evil.test", "amazon.com", "smile.amazon.pl", "amazon.pl.evil.test",
            "evilamazon.pl", "wwwamazon.pl", "amazon.pl.", "www.amazon.pl.",
            "amazon.pl:443", "amazon.pl:80", "amazon.pl:", "amazon.pl:bad",
            "user@amazon.pl", "user:password@amazon.pl", "@amazon.pl",
            "amazon.pl@evil.test", "evil.test@amazon.pl", "amazon.pl%00.evil.test",
            "amazon%2epl", "127.0.0.1", "2130706433", "[::1]", "[amazon.pl",
            "аmazon.pl", "amazon。pl", "amazon.pl\\@evil.test",
        )
        urls = [f"https://{host}/dp/{ASIN}" for host in authorities]
        urls += [
            f"http://amazon.pl/dp/{ASIN}", f"ftp://amazon.pl/dp/{ASIN}",
            f"//amazon.pl/dp/{ASIN}", f"https:amazon.pl/dp/{ASIN}",
            f"https:///amazon.pl/dp/{ASIN}", f"https:////amazon.pl/dp/{ASIN}",
            f"https://amazon.pl\\dp\\{ASIN}",
        ]
        for url in urls:
            with self.subTest(url=url), self.assertRaises(InvalidProductURL):
                parse_amazon_url(url)

    def test_rejects_unsupported_encoded_and_ambiguous_paths(self):
        paths = (
            "", "/", "/dp", "/dp/", f"/DP/{ASIN}", f"/title/dp/{ASIN}",
            f"/dp/{ASIN}/", f"/dp/{ASIN}/ref=test", f"//dp/{ASIN}",
            f"/gp/product/{ASIN}/", f"/gp/aw/d/{ASIN}", f"/dp/{ASIN}/dp/{ASIN}",
            f"/dp/{ASIN};x", f"/dp/{ASIN},0123456789", f"/dp/{ASIN}/../0123456789",
            f"/../dp/{ASIN}", f"/./dp/{ASIN}", f"/%2e%2e/dp/{ASIN}",
            f"/dp%2f{ASIN}", f"/dp%2F{ASIN}", f"/dp%5c{ASIN}",
            f"/dp/%42{ASIN[1:]}", f"/dp/{ASIN}%00", f"/dp/{ASIN}%252f",
            "/dp/B01234567", "/dp/B0123456789", "/dp/B01234567_",
            "/dp/B01234567-", "/dp/B01234567ſ", "/dp/B0123456ß",
            "/dp/Ｂ012345678", "/dp/B01234567١",
            f"/gp/slredirect/picassoRedirect.html?url=/dp/{ASIN}",
            f"/redirect?url=https://amazon.pl/dp/{ASIN}",
        )
        for path in paths:
            with self.subTest(path=path), self.assertRaises(InvalidProductURL):
                parse_amazon_url(f"https://amazon.pl{path}")

    def test_rejects_malformed_input_without_parser_cleanup(self):
        for value in (None, 1, b"https://amazon.pl/dp/B012345678", "", ASIN):
            with self.subTest(value=value), self.assertRaises(InvalidProductURL):
                parse_amazon_url(value)
        for suffix in ("#", "#details", "?x=%", "?x=%0", "?x=%GG", "?x=é", "?x=\\"):
            with self.subTest(suffix=suffix), self.assertRaises(InvalidProductURL):
                parse_amazon_url(CANONICAL + suffix)
        for character in tuple(map(chr, range(33))) + ("\x7f", "\u00a0", "\u200b"):
            for value in (
                character + CANONICAL, CANONICAL + character,
                CANONICAL.replace("amazon", f"ama{character}zon"),
                CANONICAL + "?x=" + character,
            ):
                with self.subTest(value=value), self.assertRaises(InvalidProductURL):
                    parse_amazon_url(value)

    def test_query_is_opaque_and_cannot_select_another_product_or_redirect(self):
        for query in (
            "asin=0123456789", "asin=0123456789&asin=ABCDEFGHIJ",
            "url=https://evil.test/dp/0123456789",
            "redirect=https%3A%2F%2Fevil.test", "path=%2F..%2Fdp%2F0123456789",
        ):
            with self.subTest(query=query):
                self.assertEqual(parse_amazon_url(CANONICAL + "?" + query).canonical_url, CANONICAL)

    def test_parser_never_uses_network(self):
        with (
            patch("socket.getaddrinfo", side_effect=AssertionError("DNS forbidden")),
            patch("socket.socket", side_effect=AssertionError("Network forbidden")),
            patch("urllib.request.urlopen", side_effect=AssertionError("Fetch forbidden")),
        ):
            self.assertEqual(parse_amazon_url(CANONICAL).canonical_url, CANONICAL)
            with self.assertRaises(InvalidProductURL):
                parse_amazon_url("https://amzn.to/example")

    def test_shared_asin_validation_preserves_repository_whitespace_support(self):
        self.assertIs(repository_normalize_asin, normalize_asin)
        self.assertEqual(normalize_asin(" b012345678 "), ASIN)
        for value in (
            "B01234567ſ", "B0123456ß", "Ｂ012345678", "B01234567١",
            "B01234567", "B0123456789", "B0123 5678", None, 123,
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_asin(value)

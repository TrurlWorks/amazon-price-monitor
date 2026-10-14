import asyncio
import os
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from httpx import ConnectError, MockTransport, Response
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.amazon_page_provider import AmazonPageProvider
from backend.config import Settings
from backend.main import create_app
from backend.mock_provider import MockAmazonProvider
from backend.models import AcquisitionAttempt, PriceSnapshot, Product, RefreshRequest, naive_utc, utcnow
from backend.providers import (
    AmazonBlocked,
    Availability,
    ProductNotFound,
    ProviderError,
    ProviderUnavailable,
    TransientProviderError,
)
from backend.services import ProductService
from backend.worker import refresh_due
from threading import Event

ROOT = Path(__file__).resolve().parents[1]
URL = "https://amazon.pl/dp/B012345678"


class FailingProvider(MockAmazonProvider):
    error = None
    metadata_error = None

    async def get_product(self, asin):
        if self.metadata_error:
            raise self.metadata_error
        return await super().get_product(asin)

    async def get_offer(self, asin):
        if self.error:
            raise self.error
        return await super().get_offer(asin)


class ProductAPITests(TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        environment = patch.dict(os.environ, {"MONITOR_DATA_DIR": directory.name})
        environment.start()
        self.addCleanup(environment.stop)
        command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
        self.provider = FailingProvider()
        settings = Settings(data_dir=Path(directory.name)).model_copy(
            update={"queue_gap_seconds": 0},
        )
        self.app = create_app(settings, self.provider)
        self.client = self.enterContext(TestClient(self.app))

    def add(self):
        response = self.client.post("/api/products?check_now=false", json={"url": URL})
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["queue_state"], "manual")
        self.run_queue()
        return self.client.get(f"/api/products/{response.json()['id']}").json()

    def run_queue(self):
        asyncio.run(refresh_due(
            self.app.state.database, self.app.state.product_provider,
            self.app.state.settings, Event(),
        ))

    def refresh(self, path):
        response = self.client.post(path + "/refresh")
        self.assertEqual(response.status_code, 202, response.text)
        self.run_queue()
        return self.client.get(path)

    def history(self, product_id):
        response = self.client.get(f"/api/products/{product_id}/history")
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_page_refresh_upgrades_mock_metadata_and_preserves_history(self):
        product = self.add()
        product_id = product["id"]
        original = self.history(product_id)["snapshots"]
        html = (ROOT / "tests/fixtures/amazon_product.html").read_text(encoding="utf-8")
        requests = []

        def respond(request):
            requests.append(request)
            return Response(200, text=html)

        self.app.state.product_provider = AmazonPageProvider(
            transport=MockTransport(respond),
        )
        path = f"/api/products/{product_id}"
        for count in (1, 2):
            response = self.refresh(path)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(len(requests), count)
            self.assertEqual(response.json()["title"], "Prawdziwy produkt & akcesoria")
            self.assertEqual(
                response.json()["image_url"], "https://m.media-amazon.com/images/I/main.jpg",
            )
            history = self.history(product_id)["snapshots"]
            self.assertEqual(history[:1], original)
            self.assertEqual(len(history), count + 1)
            self.assertEqual(history[-1]["price"], "1234.56")
        html = (ROOT / "tests/fixtures/amazon_captcha.html").read_text(encoding="utf-8")
        before = self.client.get(path).json()
        self.assertEqual(self.refresh(path).status_code, 200)
        after = self.client.get(path).json()
        self.assertEqual(after["title"], before["title"])
        self.assertEqual(after["image_url"], before["image_url"])
        self.assertEqual(self.history(product_id)["snapshots"], history)

    def test_patch_stop_start_preserves_product_and_history(self):
        product = self.add()
        product_id = product["id"]
        path = f"/api/products/{product_id}"
        history = self.history(product_id)
        for active in (False, False, True, True):
            with self.subTest(active=active):
                response = self.client.patch(path, json={"is_active": active})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["is_active"], active)
                self.assertEqual(
                    response.json()["pause_reason"], None if active else "manual",
                )
                self.assertEqual(self.client.get(path).json(), response.json())
                self.assertEqual(self.history(product_id), history)
                self.assertEqual(self.provider.observations["B012345678"], 1)
                if not active:
                    with Session(self.app.state.database) as session:
                        asyncio.run(ProductService(session, self.provider).refresh(
                            product_id, automated=True,
                        ))
                    self.assertEqual(self.provider.observations["B012345678"], 1)
        with Session(self.app.state.database) as session:
            asyncio.run(ProductService(session, self.provider).refresh(
                product_id, automated=True,
            ))
        self.assertEqual(self.provider.observations["B012345678"], 2)
        self.assertEqual(len(self.history(product_id)["snapshots"]), 2)

    def test_patch_accepts_only_boolean_is_active(self):
        product = self.add()
        path = f"/api/products/{product['id']}"
        for body in (
            {}, {"is_active": None}, {"is_active": 0}, {"is_active": 1},
            {"is_active": "false"}, {"is_active": []}, {"is_active": {}},
            {"is_active": False, "title": "changed"}, {"status": "ACTIVE"},
        ):
            with self.subTest(body=body):
                response = self.client.patch(path, json=body)
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(self.client.get(path).json(), product)
        self.assertEqual(self.provider.observations["B012345678"], 1)
        self.assertEqual(len(self.history(product["id"])["snapshots"]), 1)

    def test_patch_missing_product_and_invalid_ids(self):
        for active in (False, True):
            response = self.client.patch("/api/products/999", json={"is_active": active})
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json(), {"detail": "product_not_found"})
        for value in ("0", "-1", "abc"):
            response = self.client.patch(
                f"/api/products/{value}", json={"is_active": False},
            )
            self.assertEqual(response.status_code, 422)

    def test_mock_observations_survive_application_restart(self):
        asin = "B012345678"
        settings = self.app.state.settings
        product_id = None
        for index, status in enumerate(("ACTIVE", "UNKNOWN", "UNAVAILABLE", "ACTIVE")):
            provider = MockAmazonProvider("temporary")
            provider.observations[asin] = 20
            app = create_app(settings, provider)
            with TestClient(app) as client:
                if product_id is None:
                    response = client.post("/api/products?check_now=false", json={"url": URL})
                    self.assertEqual(response.status_code, 201, response.text)
                    product_id = response.json()["id"]
                else:
                    response = client.post(f"/api/products/{product_id}/refresh")
                    self.assertEqual(response.status_code, 202, response.text)
                asyncio.run(refresh_due(app.state.database, provider, settings, Event()))
                self.assertEqual(
                    client.get(f"/api/products/{product_id}").json()["status"], status,
                )
                with Session(app.state.database) as session:
                    snapshots = list(session.scalars(
                        select(PriceSnapshot)
                        .where(PriceSnapshot.product_id == product_id)
                        .order_by(PriceSnapshot.id)
                    ))
                    self.assertEqual(len(snapshots), index + 1)
                    for observation, snapshot in enumerate(snapshots):
                        expected = provider.offer_at(asin, observation)
                        self.assertEqual(snapshot.price, expected.price)
                        self.assertEqual(
                            snapshot.checked_at, expected.checked_at.replace(tzinfo=None),
                        )

    def test_crud_duplicate_and_history(self):
        self.assertEqual(self.client.get("/api/products").json(), [])
        product = self.add()
        product_id = product["id"]
        self.assertEqual(product["status"], "ACTIVE")
        self.assertEqual(product["amazon_url"], "https://www.amazon.pl/dp/B012345678")
        self.assertEqual(self.client.get(f"/api/products/{product_id}").json(), product)
        self.assertEqual(self.client.get("/api/products").json(), [product])
        alternate = "https://www.amazon.pl/gp/product/b012345678?tag=test"
        response = self.client.post("/api/products", json={"url": alternate})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), {"detail": "duplicate_asin"})
        self.assertEqual(self.provider.observations["B012345678"], 1)
        self.assertEqual(len(self.history(product_id)["snapshots"]), 1)
        response = self.refresh(f"/api/products/{product_id}")
        self.assertEqual(response.status_code, 200)
        history = self.history(product_id)
        self.assertEqual(len(history["snapshots"]), 2)
        self.assertEqual(history["stats"]["change_amount"], "0.00")
        response = self.client.delete(f"/api/products/{product_id}")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b"")
        self.assertEqual(self.client.get("/api/products").json(), [])
        with Session(self.app.state.database) as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(PriceSnapshot)), 0)
        self.assertEqual(self.client.get("/api/health").status_code, 200)

    def test_add_and_repeated_manual_checks_share_one_queued_request(self):
        response = self.client.post("/api/products?check_now=false", json={"url": URL})
        self.assertEqual(response.status_code, 201)
        product_id = response.json()["id"]
        path = f"/api/products/{product_id}"
        self.assertEqual(response.json()["queue_state"], "manual")
        self.assertIsNone(response.json()["last_checked_at"])
        self.assertEqual(self.provider.observations, {})
        self.assertEqual(self.history(product_id)["snapshots"], [])
        for _ in range(3):
            self.assertEqual(self.client.post(path + "/refresh").status_code, 202)
        with Session(self.app.state.database) as session:
            self.assertEqual(session.query(RefreshRequest).count(), 1)
        self.run_queue()
        self.assertEqual(self.provider.observations["B012345678"], 1)
        self.assertEqual(len(self.history(product_id)["snapshots"]), 1)

    def test_add_reads_immediately_and_schedules_the_next_regular_check(self):
        response = self.client.post("/api/products", json={"url": URL})
        self.assertEqual(response.status_code, 201, response.text)
        product = response.json()
        self.assertEqual(product["queue_state"], "regular")
        self.assertIsNotNone(product["last_checked_at"])
        self.assertEqual(self.provider.observations[product["asin"]], 1)
        self.assertEqual(len(self.history(product["id"])["snapshots"]), 1)
        with Session(self.app.state.database) as session:
            request = session.get(RefreshRequest, product["id"])
            self.assertGreater(request.due_at, naive_utc(utcnow()))
            self.assertEqual(session.query(AcquisitionAttempt).count(), 1)
        self.run_queue()
        self.assertEqual(self.provider.observations[product["asin"]], 1)

    def test_blocked_first_read_keeps_product_and_queues_a_delayed_retry(self):
        self.provider.error = AmazonBlocked("private challenge detail")
        response = self.client.post("/api/products", json={"url": URL})
        self.assertEqual(response.status_code, 201, response.text)
        self.assertNotIn("private challenge detail", response.text)
        product = response.json()
        self.assertEqual(product["queue_state"], "retry")
        self.assertEqual(product["consecutive_failures"], 1)
        self.assertEqual(product["automatic_failures"], 1)
        self.assertEqual(self.history(product["id"])["snapshots"], [])
        with Session(self.app.state.database) as session:
            request = session.get(RefreshRequest, product["id"])
            self.assertGreater(request.due_at, naive_utc(utcnow()))
            attempt = session.scalar(select(AcquisitionAttempt))
            self.assertEqual(attempt.outcome, "blocked")
            request.due_at = naive_utc(utcnow())
            session.commit()
        self.provider.error = None
        self.run_queue()
        self.assertEqual(len(self.history(product["id"])["snapshots"]), 1)
        self.assertEqual(self.client.get(f"/api/products/{product['id']}").json()["queue_state"], "regular")

    def test_refresh_all_routes_are_unavailable(self):
        routes = {route.path for route in self.app.routes}
        self.assertNotIn("/api/products/refresh-all", routes)
        self.assertNotIn("/api/products/refresh-status", routes)

    def test_validation_and_missing_resources(self):
        for body in ({}, {"url": 1}, {"url": URL, "extra": True}, {"url": "http://evil.test"}):
            response = self.client.post("/api/products", json=body)
            self.assertEqual(response.status_code, 422)
        self.assertEqual(self.provider.observations, {})
        for method, suffix in (("get", ""), ("delete", ""), ("post", "/refresh"),
                               ("get", "/history")):
            response = getattr(self.client, method)(f"/api/products/999{suffix}")
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json(), {"detail": "product_not_found"})
        for value in ("0", "-1", "abc"):
            self.assertEqual(self.client.get(f"/api/products/{value}").status_code, 422)
        product_id = self.add()["id"]
        response = self.client.get(f"/api/products/{product_id}/history?currency=invalid")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json(), {"detail": "invalid_currency"})
        self.assertEqual(
            self.client.get(f"/api/products/{product_id}/history?currency=EUR").json()["snapshots"],
            [],
        )

    def test_provider_failure_keeps_pending_product_without_observation(self):
        for operation in ("error", "metadata_error"):
            for error in (ProductNotFound, ProviderUnavailable, TransientProviderError):
                with self.subTest(operation=operation, error=error):
                    setattr(self.provider, operation, error("private information"))
                    response = self.client.post("/api/products?check_now=false", json={"url": URL})
                    self.assertEqual(response.status_code, 201)
                    self.assertNotIn("private information", response.text)
                    self.run_queue()
                    product_id = response.json()["id"]
                    self.assertEqual(self.history(product_id)["snapshots"], [])
                    self.assertEqual(
                        self.client.get(f"/api/products/{product_id}").json()[
                            "consecutive_failures"
                        ], 1,
                    )
                    self.client.delete(f"/api/products/{product_id}")
                    setattr(self.provider, operation, None)
        self.add()

    def test_snapshot_write_failure_keeps_product_without_observation(self):
        response = self.client.post("/api/products?check_now=false", json={"url": URL})
        self.assertEqual(response.status_code, 201)
        with patch(
            "backend.services.SQLAlchemySnapshotRepository.append",
            side_effect=ValueError("invalid offer"),
        ):
            self.run_queue()
        product_id = response.json()["id"]
        self.assertEqual(self.history(product_id)["snapshots"], [])
        self.assertEqual(
            self.client.get(f"/api/products/{product_id}").json()["consecutive_failures"],
            1,
        )

    def test_failure_transitions_preserve_history_and_recover(self):
        product_id = self.add()["id"]
        path = f"/api/products/{product_id}"
        initial = self.history(product_id)["snapshots"]
        for error, status, failures, missing in (
            (TransientProviderError, "UNKNOWN", 1, 0),
            (ProductNotFound, "UNKNOWN", 2, 1),
            (ProductNotFound, "UNKNOWN", 3, 2),
            (ProductNotFound, "NOT_FOUND", 4, 3),
            (ProductNotFound, "NOT_FOUND", 5, 4),
            (ProviderUnavailable, "UNKNOWN", 6, 0),
            (ProductNotFound, "UNKNOWN", 7, 1),
            (ProviderError, "UNKNOWN", 8, 0),
            (ConnectError, "UNKNOWN", 9, 0),
            (TimeoutError, "UNKNOWN", 10, 0),
        ):
            self.provider.error = error("private")
            response = self.refresh(path)
            self.assertEqual(response.status_code, 200)
            product = self.client.get(path).json()
            self.assertEqual(product["status"], status)
            self.assertEqual(product["consecutive_failures"], failures)
            self.assertEqual(product["automatic_failures"], 0)
            self.assertEqual(product["consecutive_not_found"], missing)
            self.assertEqual(self.history(product_id)["snapshots"], initial)
        self.provider.error = None
        product = self.refresh(path).json()
        self.assertEqual(product["status"], "ACTIVE")
        self.assertEqual(product["consecutive_failures"], 0)
        self.assertEqual(product["automatic_failures"], 0)
        self.assertEqual(product["consecutive_not_found"], 0)
        self.assertEqual(len(self.history(product_id)["snapshots"]), 2)

    def test_unavailable_offer_and_recovery_are_observations(self):
        self.provider.scenario = "temporary"
        product_id = self.add()["id"]
        for status in ("UNKNOWN", "UNAVAILABLE", "ACTIVE"):
            product = self.refresh(f"/api/products/{product_id}").json()
            self.assertEqual(product["status"], status)
            self.assertEqual(product["consecutive_failures"], 0)
            self.assertEqual(product["consecutive_not_found"], 0)
        history = self.history(product_id)["snapshots"]
        self.assertEqual(len(history), 4)
        self.assertEqual([s["price"] for s in history[1:3]], [None, None])

    def test_automated_refresh_skips_inactive_manual_refresh_does_not(self):
        product_id = self.add()["id"]
        with Session(self.app.state.database, expire_on_commit=False) as session:
            product = session.get(Product, product_id)
            product.is_active = False
            session.commit()
            service = ProductService(session, self.provider)
            asyncio.run(service.refresh(product_id, automated=True))
        self.assertEqual(self.provider.observations["B012345678"], 1)
        response = self.refresh(f"/api/products/{product_id}")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["is_active"])
        self.assertEqual(len(self.history(product_id)["snapshots"]), 2)

    def test_recovered_scenario_can_be_added_without_price(self):
        self.provider.scenario = "recovered"
        product = self.add()
        self.assertEqual(product["status"], "UNKNOWN")
        self.assertIsNone(self.history(product["id"])["snapshots"][0]["price"])

    def test_threshold_configuration(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings()
            self.assertEqual(settings.not_found_threshold, 3)
            self.assertEqual(settings.unavailable_threshold, 2)
        with patch.dict(os.environ, {
            "MONITOR_NOT_FOUND_THRESHOLD": "2",
            "MONITOR_UNAVAILABLE_THRESHOLD": "3",
        }):
            settings = Settings()
            self.assertEqual(settings.not_found_threshold, 2)
            self.assertEqual(settings.unavailable_threshold, 3)
        for field in ("not_found_threshold", "unavailable_threshold"):
            for value in (0, -1):
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValidationError):
                        Settings(**{field: value})

    def test_custom_thresholds_reach_api_and_preserve_duplicate_observations(self):
        self.app.state.settings = self.app.state.settings.model_copy(update={
            "not_found_threshold": 2, "unavailable_threshold": 3,
        })
        self.provider.scenario = "recovered"
        product_id = self.add()["id"]
        path = f"/api/products/{product_id}"
        offer = self.provider.offer_at("B012345678", 0)
        with patch.object(self.provider, "get_offer", return_value=offer):
            for status in ("UNKNOWN", "UNAVAILABLE", "UNAVAILABLE"):
                response = self.refresh(path)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["status"], status)
        initial = self.history(product_id)["snapshots"]
        self.assertEqual(len(initial), 4)
        self.assertEqual(len({item["id"] for item in initial}), 4)
        self.provider.error = ProductNotFound()
        for status in ("UNKNOWN", "NOT_FOUND"):
            self.assertEqual(self.refresh(path).status_code, 200)
            self.assertEqual(self.client.get(path).json()["status"], status)
            self.assertEqual(self.history(product_id)["snapshots"], initial)

    def test_observation_streak_uses_insertion_order_and_all_currencies(self):
        product_id = self.add()["id"]
        path = f"/api/products/{product_id}"
        self.provider.scenario = "recovered"
        unavailable = self.provider.offer_at("B012345678", 0)
        available = self.provider.offer_at("B012345678", 2)
        unknown = replace(unavailable, availability=Availability.UNKNOWN)
        for offer, status in (
            (unavailable, "UNKNOWN"),
            (replace(unavailable, currency="EUR"), "UNAVAILABLE"),
            (unknown, "UNKNOWN"),
            (unavailable, "UNKNOWN"),
            (unavailable, "UNAVAILABLE"),
            (available, "ACTIVE"),
            (unavailable, "UNKNOWN"),
        ):
            with self.subTest(status=status, offer=offer):
                with patch.object(self.provider, "get_offer", return_value=offer):
                    response = self.refresh(path)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["status"], status)
        self.assertEqual(len(self.history(product_id)["snapshots"]), 7)

    def test_valid_observation_resets_absence_and_failures(self):
        product_id = self.add()["id"]
        path = f"/api/products/{product_id}"
        self.provider.error = ProductNotFound()
        for _ in range(3):
            self.assertEqual(self.refresh(path).status_code, 200)
        self.provider.error = None
        self.provider.scenario = "recovered"
        offer = self.provider.offer_at("B012345678", 0)
        with patch.object(self.provider, "get_offer", return_value=offer):
            product = self.refresh(path).json()
        self.assertEqual(product["status"], "UNKNOWN")
        self.assertEqual(product["consecutive_failures"], 0)
        self.assertEqual(product["consecutive_not_found"], 0)
        initial = self.history(product_id)["snapshots"]
        self.provider.error = ProductNotFound()
        self.assertEqual(self.refresh(path).status_code, 200)
        product = self.client.get(path).json()
        self.assertEqual(product["status"], "UNKNOWN")
        self.assertEqual(product["consecutive_not_found"], 1)
        self.assertEqual(self.history(product_id)["snapshots"], initial)
        self.provider.error = None
        with patch.object(self.provider, "get_offer", return_value=offer):
            product = self.refresh(path).json()
        self.assertEqual(product["status"], "UNAVAILABLE")
        self.assertEqual(product["consecutive_failures"], 0)
        self.assertEqual(product["consecutive_not_found"], 0)

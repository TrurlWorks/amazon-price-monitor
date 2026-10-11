import asyncio
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from unittest import TestCase
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.config import Settings
from backend.database import create_database
from backend.mock_provider import MockAmazonProvider
from backend.models import PriceSnapshot, Product, QueueState, RefreshRequest, naive_utc
from backend.providers import AmazonBlocked, ProviderError
from backend.repositories import (
    SQLAlchemyProductRepository,
    set_runtime_intervals,
)
from backend.services import ProductService
from backend.worker import main, refresh_due

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 18, 12, tzinfo=UTC)


class WorkerTests(TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        environment = patch.dict(os.environ, {"MONITOR_DATA_DIR": directory.name})
        environment.start()
        self.addCleanup(environment.stop)
        command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
        self.settings = Settings(data_dir=Path(directory.name))
        self.settings = self.settings.model_copy(update={"queue_gap_seconds": 0})
        self.engine = create_database(self.settings)
        self.addCleanup(self.engine.dispose)
        self.stop = Event()

    def add_product(self, asin, checked_at=None, active=True):
        with Session(self.engine) as session:
            product = SQLAlchemyProductRepository(session).add(asin)
            product.last_checked_at = checked_at
            product.is_active = active
            product_id = product.id
            session.commit()
            return product_id

    def run_due(self, provider, now=NOW):
        with (
            patch("backend.worker.utcnow", return_value=now),
            patch("backend.services.utcnow", return_value=now),
            patch("backend.acquisition_queue.offset_seconds", return_value=0),
        ):
            asyncio.run(refresh_due(self.engine, provider, self.settings, self.stop))

    def test_main_uses_configured_poll_interval(self):
        cutoff = naive_utc(NOW) - timedelta(seconds=60)
        due = self.add_product("B000000001", cutoff)
        self.add_product("B000000002", cutoff + timedelta(microseconds=1))
        self.add_product("B000000003", cutoff, active=False)

        async def run_once(engine, provider, settings, stop):
            await refresh_due(engine, provider, settings, stop)
            stop.set()

        with (
            patch.dict(os.environ, {"POLL_INTERVAL_SECONDS": "60"}),
            patch("backend.worker.Event", return_value=self.stop),
            patch("backend.worker.signal.signal"),
            patch("backend.worker.utcnow", return_value=NOW),
            patch("backend.services.utcnow", return_value=NOW),
            patch("backend.worker.refresh_due", side_effect=run_once) as refresh,
            patch("backend.acquisition_queue.offset_seconds", return_value=0),
        ):
            main()
        refresh.assert_awaited_once()
        with Session(self.engine) as session:
            self.assertEqual(
                list(session.scalars(select(PriceSnapshot.product_id))), [due],
            )

    def test_runtime_intervals_are_used_without_worker_restart(self):
        product_id = self.add_product(
            "B000000001", naive_utc(NOW) - timedelta(seconds=120),
        )
        self.run_due(MockAmazonProvider())
        with Session(self.engine) as session:
            self.assertEqual(list(session.scalars(select(PriceSnapshot.id))), [])
            set_runtime_intervals(
                session, poll_interval_seconds=60, failed_retry_seconds=120,
            )
            session.commit()
        self.run_due(MockAmazonProvider())
        with Session(self.engine) as session:
            self.assertEqual(
                list(session.scalars(select(PriceSnapshot.product_id))), [product_id],
            )

    def test_due_selection_and_persisted_attempts(self):
        cutoff = naive_utc(NOW) - timedelta(seconds=21600)
        never = self.add_product("B000000001")
        overdue = self.add_product("B000000002", cutoff - timedelta(seconds=1))
        boundary = self.add_product("B000000003", cutoff)
        self.add_product("B000000004", cutoff + timedelta(microseconds=1))
        self.add_product("B000000005", active=False)
        self.add_product("B000000006", cutoff, active=False)
        self.run_due(MockAmazonProvider())
        with Session(self.engine) as session:
            self.assertEqual(
                list(session.scalars(
                    select(PriceSnapshot.product_id).order_by(PriceSnapshot.id)
                )),
                [overdue, never, boundary],
            )
            for product_id in (never, overdue, boundary):
                self.assertEqual(
                    session.get(Product, product_id).last_checked_at, naive_utc(NOW),
                )
        # A new provider and new sessions must still respect persisted scheduling.
        self.run_due(MockAmazonProvider())
        with Session(self.engine) as session:
            self.assertEqual(len(list(session.scalars(select(PriceSnapshot)))), 3)

    def test_provider_failure_isolated_in_independent_sessions(self):
        failed = self.add_product("B000000001")
        succeeded = self.add_product("B000000002")
        sessions = []
        original = ProductService.refresh

        class FailingProvider(MockAmazonProvider):
            async def get_offer(self, asin):
                if asin == "B000000001":
                    raise ProviderError("fixture failure")
                return await super().get_offer(asin)

        async def track(service, product_id, *, automated=False):
            self.assertTrue(automated)
            sessions.append(service.session)
            return await original(service, product_id, automated=automated)

        with patch.object(ProductService, "refresh", new=track):
            self.run_due(FailingProvider())
        self.assertEqual(len(sessions), 2)
        self.assertIsNot(sessions[0], sessions[1])
        with Session(self.engine) as session:
            product = session.get(Product, failed)
            self.assertEqual(product.consecutive_failures, 1)
            self.assertEqual(product.last_checked_at, naive_utc(NOW))
            self.assertEqual(
                list(session.scalars(select(PriceSnapshot.product_id))), [succeeded],
            )
        self.run_due(FailingProvider())
        with Session(self.engine) as session:
            self.assertEqual(session.get(Product, failed).consecutive_failures, 1)

    def test_failed_retries_and_success_restore_normal_schedule(self):
        class FailingProvider(MockAmazonProvider):
            failing = False
            attempts = 0

            async def get_offer(self, asin):
                self.attempts += 1
                if self.failing:
                    raise ProviderError("fixture failure")
                return await super().get_offer(asin)

        for retry in (60, 120):
            with self.subTest(retry=retry):
                start_at = NOW + timedelta(days=1 if retry == 120 else 0)
                self.settings = self.settings.model_copy(update={
                    "poll_interval_seconds": 21600,
                    "failed_retry_seconds": retry,
                })
                product_id = self.add_product(f"B{retry:09d}")
                provider = FailingProvider()
                self.run_due(provider, start_at)
                with Session(self.engine) as session:
                    original_ids = list(session.scalars(
                        select(PriceSnapshot.id)
                        .where(PriceSnapshot.product_id == product_id)
                    ))
                self.assertEqual(len(original_ids), 1)
                provider.failing = True
                failure_at = start_at + timedelta(seconds=21600)
                self.run_due(provider, failure_at)
                for failures in (1, 2):
                    with Session(self.engine) as session:
                        product = session.get(Product, product_id)
                        self.assertEqual(product.consecutive_failures, failures)
                        self.assertEqual(product.last_checked_at, naive_utc(failure_at))
                        self.assertEqual(list(session.scalars(
                            select(PriceSnapshot.id)
                            .where(PriceSnapshot.product_id == product_id)
                        )), original_ids)
                    attempts = provider.attempts
                    boundary = failure_at + timedelta(seconds=retry * failures)
                    self.run_due(provider, boundary - timedelta(microseconds=1))
                    self.assertEqual(provider.attempts, attempts)
                    provider.failing = failures == 1
                    self.run_due(provider, boundary)
                    self.assertEqual(provider.attempts, attempts + 1)
                    failure_at = boundary
                with Session(self.engine) as session:
                    self.assertEqual(session.get(Product, product_id).consecutive_failures, 0)
                    self.assertEqual(session.get(Product, product_id).automatic_failures, 0)
                attempts = provider.attempts
                self.run_due(provider, failure_at + timedelta(seconds=retry))
                self.run_due(provider, failure_at + timedelta(seconds=21600, microseconds=-1))
                self.assertEqual(provider.attempts, attempts)
                self.run_due(provider, failure_at + timedelta(seconds=21600))
                self.assertEqual(provider.attempts, attempts + 1)
                with Session(self.engine) as session:
                    ids = list(session.scalars(
                        select(PriceSnapshot.id)
                        .where(PriceSnapshot.product_id == product_id)
                        .order_by(PriceSnapshot.id)
                    ))
                    self.assertEqual(ids[:1], original_ids)
                    self.assertEqual(len(ids), 3)
                    session.get(Product, product_id).is_active = False
                    session.commit()

    def test_two_failed_automatic_retries_pause_product_then_recover(self):
        product_id = self.add_product("B000000001")
        with Session(self.engine) as session:
            set_runtime_intervals(
                session, poll_interval_seconds=21600, failed_retry_seconds=120,
            )
            session.commit()

        class FailingProvider(MockAmazonProvider):
            attempts = 0
            failing = True

            async def get_offer(self, asin):
                self.attempts += 1
                if self.failing:
                    raise ProviderError("fixture failure")
                return await super().get_offer(asin)

        provider = FailingProvider()
        for failure, elapsed in ((1, 0), (2, 120), (3, 360)):
            attempt_at = NOW + timedelta(seconds=elapsed)
            self.run_due(provider, attempt_at)
            self.assertEqual(provider.attempts, failure)
            with Session(self.engine) as session:
                product = session.get(Product, product_id)
                self.assertEqual(product.automatic_failures, failure)
                self.assertEqual(product.consecutive_failures, failure)
                self.assertEqual(product.last_checked_at, naive_utc(attempt_at))
                self.assertEqual(product.is_active, failure < 3)
                self.assertEqual(list(session.scalars(select(PriceSnapshot))), [])
            self.run_due(provider, attempt_at + timedelta(seconds=119))
            self.assertEqual(provider.attempts, failure)
        self.run_due(provider, NOW + timedelta(hours=1))
        self.assertEqual(provider.attempts, 3)

        with Session(self.engine) as session:
            request = session.get(RefreshRequest, product_id)
            self.assertEqual(request.kind, "recovery")
            recovery_at = request.due_at.replace(tzinfo=UTC)
        self.run_due(provider, recovery_at - timedelta(seconds=1))
        self.assertEqual(provider.attempts, 3)
        provider.failing = False
        self.run_due(provider, recovery_at)
        self.assertEqual(provider.attempts, 4)
        with Session(self.engine) as session:
            product = session.get(Product, product_id)
            self.assertTrue(product.is_active)
            self.assertIsNone(product.pause_reason)
            self.assertEqual(product.automatic_failures, 0)
            self.assertEqual(product.consecutive_failures, 0)
            self.assertEqual(session.get(RefreshRequest, product_id).kind, "regular")
            self.assertEqual(len(list(session.scalars(select(PriceSnapshot)))), 1)

    def test_shutdown_skips_pending_products(self):
        self.add_product("B000000001")
        self.stop.set()
        self.run_due(MockAmazonProvider())
        with Session(self.engine) as session:
            self.assertEqual(list(session.scalars(select(PriceSnapshot))), [])

    def test_global_spacing_persists_between_worker_runs(self):
        first = self.add_product("B000000001")
        second = self.add_product("B000000002")
        self.settings = self.settings.model_copy(update={"queue_gap_seconds": 180})
        provider = MockAmazonProvider()
        self.run_due(provider)
        with Session(self.engine) as session:
            self.assertEqual(list(session.scalars(select(PriceSnapshot.product_id))), [first])
            self.assertEqual(session.get(QueueState, 1).last_started_at, naive_utc(NOW))
        self.run_due(provider, NOW + timedelta(seconds=179))
        with Session(self.engine) as session:
            self.assertEqual(list(session.scalars(select(PriceSnapshot.product_id))), [first])
        self.run_due(provider, NOW + timedelta(seconds=180))
        with Session(self.engine) as session:
            self.assertEqual(
                list(session.scalars(select(PriceSnapshot.product_id))), [first, second],
            )

    def test_two_distinct_challenges_pause_the_whole_queue(self):
        for index in range(3):
            self.add_product(f"B{index + 1:09d}")

        class BlockedProvider(MockAmazonProvider):
            attempts = 0

            async def get_offer(self, asin):
                self.attempts += 1
                raise AmazonBlocked("Amazon blocked the page request")

        provider = BlockedProvider()
        self.run_due(provider)
        self.assertEqual(provider.attempts, 2)
        with Session(self.engine) as session:
            state = session.get(QueueState, 1)
            self.assertEqual(state.cooldown_until, naive_utc(NOW + timedelta(hours=2)))
            self.assertEqual(session.query(RefreshRequest).count(), 3)
        self.run_due(provider, NOW + timedelta(hours=1))
        self.assertEqual(provider.attempts, 2)

import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.config import Settings
from backend.database import Base, create_database
from backend.models import ProductStatus, RuntimeSettings
from backend.repositories import (
    EffectiveIntervals,
    PriceStats,
    SQLAlchemyProductRepository,
    SQLAlchemySnapshotRepository,
    display_mode,
    effective_intervals,
    set_runtime_intervals,
)

ROOT = Path(__file__).resolve().parents[1]
START = datetime(2026, 1, 1, tzinfo=UTC)


class RepositoryTests(TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        environment = patch.dict(os.environ, {"MONITOR_DATA_DIR": directory.name})
        environment.start()
        self.addCleanup(environment.stop)
        self.config = Config(str(ROOT / "alembic.ini"))
        command.upgrade(self.config, "head")
        self.engine = create_database(Settings(data_dir=Path(directory.name)))
        self.addCleanup(self.engine.dispose)
        self.session = Session(self.engine)
        self.addCleanup(self.session.close)
        self.products = SQLAlchemyProductRepository(self.session)
        self.snapshots = SQLAlchemySnapshotRepository(self.session)
        self.product = self.products.add("b012345678")
        self.session.commit()

    def append(self, price, day=0, currency="PLN"):
        return self.snapshots.append(
            self.product.id, price=None if price is None else Decimal(price),
            currency=currency, checked_at=START + timedelta(days=day),
            seller="Seller", availability="AVAILABLE", is_buy_box=True,
        )

    def test_product_defaults_canonical_url_and_unique_asin(self):
        self.assertEqual(self.product.amazon_url, "https://www.amazon.pl/dp/B012345678")
        self.assertEqual(self.product.status, ProductStatus.UNKNOWN)
        self.assertTrue(self.product.is_active)
        self.assertEqual(self.product.consecutive_failures, 0)
        self.assertEqual(self.product.automatic_failures, 0)
        self.assertEqual(self.product.consecutive_not_found, 0)
        self.assertEqual(self.product.created_at, self.product.first_seen_at)
        self.assertIsNone(self.product.last_checked_at)
        self.assertEqual(self.products.get_by_asin(" b012345678 ").id, self.product.id)
        with self.assertRaises(IntegrityError), self.session.begin_nested():
            self.products.add("B012345678")

    def test_metadata_matches_migration(self):
        with self.engine.connect() as connection:
            self.assertEqual(compare_metadata(MigrationContext.configure(connection), Base.metadata), [])

    def test_runtime_intervals_fall_back_and_persist(self):
        settings = Settings().model_copy(update={
            "poll_interval_seconds": 3600,
            "failed_retry_seconds": 90,
        })
        self.assertEqual(
            effective_intervals(self.session, settings),
            EffectiveIntervals(3600, 90),
        )
        self.assertEqual(display_mode(self.session), "tiles")
        set_runtime_intervals(
            self.session, poll_interval_seconds=7200, failed_retry_seconds=120,
            display_mode="table",
        )
        self.session.commit()
        self.session.expire_all()
        self.assertEqual(
            effective_intervals(self.session, settings),
            EffectiveIntervals(7200, 120),
        )
        self.assertEqual(self.session.get(RuntimeSettings, 1).id, 1)
        self.assertEqual(display_mode(self.session), "table")

    def test_append_preserves_equal_observations_and_decimal_round_trip(self):
        first = self.append("0.10")
        second = self.append("0.10")
        self.assertNotEqual(first.id, second.id)
        self.session.commit()
        self.session.expire_all()
        history = self.snapshots.history(self.product.id, "pln")
        self.assertEqual([item.price for item in history], [Decimal("0.10")] * 2)
        self.assertEqual(history[0].seller, "Seller")
        self.assertTrue(history[0].is_buy_box)
        self.assertEqual(history[0].checked_at, START.replace(tzinfo=None))

    def test_deactivation_and_status_changes_preserve_history(self):
        self.append("10")
        self.products.set_active(self.product.id, False)
        self.product.status = ProductStatus.NOT_FOUND
        self.product.consecutive_not_found = 2
        self.session.commit()
        self.assertEqual(len(self.snapshots.history(self.product.id, "PLN")), 1)

    def test_database_rejects_update_delete_and_orphan(self):
        snapshot = self.append("10")
        self.session.commit()
        for statement in (
            "UPDATE price_snapshots SET price = 12 WHERE id = :id",
            "DELETE FROM price_snapshots WHERE id = :id",
        ):
            with self.assertRaises(IntegrityError), self.session.begin_nested():
                self.session.execute(text(statement), {"id": snapshot.id})
        with self.assertRaises(IntegrityError), self.session.begin_nested():
            self.snapshots.append(
                self.product.id + 100, price=None, currency="PLN", checked_at=START,
            )
        self.assertEqual(len(self.snapshots.history(self.product.id, "PLN")), 1)

    def test_explicit_product_deletion_cascades(self):
        product_id = self.product.id
        self.append("10")
        self.session.commit()
        self.products.delete(product_id)
        self.session.commit()
        self.assertIsNone(self.products.get(product_id))
        self.assertEqual(self.snapshots.history(product_id, "PLN"), [])

    def test_stats_order_precision_ties_and_currency_isolation(self):
        self.append("0.30", 3)
        self.append("0.10", 0)
        self.append("0.10", 2)
        self.append("0.30", 4)
        self.append("999", 5, "EUR")
        self.session.commit()
        self.session.expire_all()
        stats = self.snapshots.stats(self.product.id, "PLN")
        self.assertEqual(stats.initial, Decimal("0.10"))
        self.assertEqual(stats.current, Decimal("0.30"))
        self.assertEqual(stats.change_amount, Decimal("0.20"))
        self.assertEqual(stats.change_percent, Decimal("200"))
        self.assertEqual(stats.average, Decimal("0.20"))
        self.assertEqual(stats.minimum, Decimal("0.10"))
        self.assertEqual(stats.maximum, Decimal("0.30"))
        self.assertEqual(stats.minimum_at, START.replace(tzinfo=None))
        self.assertEqual(stats.maximum_at, (START + timedelta(days=3)).replace(tzinfo=None))

    def test_missing_prices_and_zero_initial(self):
        self.assertEqual(self.snapshots.stats(self.product.id, "PLN"), PriceStats())
        self.append(None)
        self.assertEqual(self.snapshots.stats(self.product.id, "PLN"), PriceStats())
        self.append("10", 1)
        stats = self.snapshots.stats(self.product.id, "PLN")
        self.assertIsNone(stats.initial)
        self.assertIsNone(stats.change_amount)
        self.assertIsNone(stats.change_percent)
        self.assertEqual(stats.average, Decimal("10"))
        self.append(None, 2)
        self.assertIsNone(self.snapshots.stats(self.product.id, "PLN").current)
        self.append("0", 0, "EUR")
        self.append("10", 1, "EUR")
        stats = self.snapshots.stats(self.product.id, "EUR")
        self.assertEqual(stats.change_amount, Decimal("10"))
        self.assertIsNone(stats.change_percent)

    def test_input_validation_and_counters(self):
        for price in (0.1, Decimal("NaN"), Decimal("-1"), Decimal("0.001")):
            with self.assertRaises(ValueError):
                self.snapshots.append(
                    self.product.id, price=price, currency="PLN", checked_at=START,
                )
        with self.assertRaises(ValueError):
            self.snapshots.append(
                self.product.id, price=None, currency="PLN",
                checked_at=START.replace(tzinfo=None),
            )
        with self.assertRaises(ValueError):
            self.products.add("invalid")
        with self.assertRaises(IntegrityError), self.session.begin_nested():
            self.product.consecutive_failures = -1
            self.session.flush()

    def test_caller_can_rollback_append(self):
        self.append("10")
        self.session.rollback()
        self.assertEqual(self.snapshots.history(self.product.id, "PLN"), [])

    def test_upgrade_preserves_existing_history(self):
        self.append("12.34")
        self.session.commit()
        command.upgrade(self.config, "head")
        self.assertEqual(self.snapshots.history(self.product.id, "PLN")[0].price, Decimal("12.34"))

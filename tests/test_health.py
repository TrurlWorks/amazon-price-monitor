import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from backend.config import Settings
from backend.database import create_database
from backend.main import create_app

ROOT = Path(__file__).resolve().parents[1]


class HealthTests(TestCase):
    """The controlled Python executor uses unittest; pytest also runs these."""

    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.settings = Settings(data_dir=Path(directory.name))

    def test_health_and_sqlite_configuration(self):
        app = create_app(self.settings)
        with TestClient(app) as client:
            response = client.get("/api/health")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"status": "ok", "database": "ok"})
            with app.state.database.connect() as connection:
                self.assertEqual(connection.scalar(text("PRAGMA journal_mode")), "wal")
                self.assertEqual(connection.scalar(text("PRAGMA foreign_keys")), 1)

    def test_database_failure_is_service_unavailable(self):
        app = create_app(self.settings)
        with TestClient(app) as client:
            with patch.object(
                app.state.database,
                "connect",
                side_effect=OperationalError("SELECT 1", {}, Exception("private detail")),
            ):
                response = client.get("/api/health")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "Database unavailable"})

    def test_migration_is_repeatable(self):
        with patch.dict(os.environ, {"MONITOR_DATA_DIR": str(self.settings.data_dir)}):
            config = Config(str(ROOT / "alembic.ini"))
            command.upgrade(config, "head")
            command.upgrade(config, "head")
            engine = create_database(self.settings)
            try:
                with engine.connect() as connection:
                    self.assertEqual(
                        connection.scalar(text("SELECT version_num FROM alembic_version")),
                        "0008",
                    )
                command.downgrade(config, "base")
                command.upgrade(config, "head")
            finally:
                engine.dispose()

    def test_retry_limit_migration_preserves_existing_product_and_history(self):
        with patch.dict(os.environ, {"MONITOR_DATA_DIR": str(self.settings.data_dir)}):
            config = Config(str(ROOT / "alembic.ini"))
            command.upgrade(config, "0005")
            engine = create_database(self.settings)
            try:
                with engine.begin() as connection:
                    connection.execute(text("""
                        INSERT INTO products
                        (asin, amazon_url, created_at, first_seen_at, consecutive_failures)
                        VALUES ('B012345678', 'https://www.amazon.pl/dp/B012345678',
                                '2026-01-01', '2026-01-01', 7)
                    """))
                    connection.execute(text("""
                        INSERT INTO price_snapshots
                        (product_id, price, currency, checked_at)
                        VALUES (1, 499.00, 'PLN', '2026-01-02')
                    """))
                command.upgrade(config, "head")
                with engine.connect() as connection:
                    self.assertEqual(connection.execute(text("""
                        SELECT consecutive_failures, automatic_failures, is_active
                        FROM products WHERE id = 1
                    """)).one(), (7, 0, 1))
                    self.assertEqual(connection.scalar(text("""
                        SELECT price FROM price_snapshots WHERE product_id = 1
                    """)), 499)
            finally:
                engine.dispose()

    def test_queue_migration_keeps_history_and_separates_pause_reasons(self):
        with patch.dict(os.environ, {"MONITOR_DATA_DIR": str(self.settings.data_dir)}):
            config = Config(str(ROOT / "alembic.ini"))
            command.upgrade(config, "0006")
            engine = create_database(self.settings)
            try:
                with engine.begin() as connection:
                    for asin, active, failures, consecutive in (
                        ("B000000001", 1, 0, 0), ("B000000002", 0, 3, 3),
                        ("B000000003", 0, 0, 0), ("B000000004", 1, 0, 1),
                    ):
                        connection.execute(text("""
                            INSERT INTO products
                            (asin, amazon_url, created_at, first_seen_at,
                             is_active, automatic_failures, consecutive_failures)
                            VALUES (:asin, :url, '2026-01-01', '2026-01-01',
                                    :active, :failures, :consecutive)
                        """), {"asin": asin, "url": f"https://www.amazon.pl/dp/{asin}",
                               "active": active, "failures": failures,
                               "consecutive": consecutive})
                    connection.execute(text("""
                        INSERT INTO price_snapshots
                        (product_id, price, currency, checked_at)
                        VALUES (1, 499.00, 'PLN', '2026-01-02')
                    """))
                command.upgrade(config, "head")
                with engine.connect() as connection:
                    self.assertEqual(connection.execute(text("""
                        SELECT id, pause_reason FROM products ORDER BY id
                    """)).all(), [(1, None), (2, "automatic"), (3, "manual"),
                                 (4, None)])
                    self.assertEqual(connection.execute(text("""
                        SELECT product_id, kind FROM refresh_requests ORDER BY product_id
                    """)).all(), [(1, "regular"), (2, "recovery"), (4, "retry")])
                    self.assertEqual(connection.scalar(text("""
                        SELECT price FROM price_snapshots WHERE product_id = 1
                    """)), 499)
            finally:
                engine.dispose()

    def test_diagnostics_migration_keeps_queue_and_price_history(self):
        with patch.dict(os.environ, {"MONITOR_DATA_DIR": str(self.settings.data_dir)}):
            config = Config(str(ROOT / "alembic.ini"))
            command.upgrade(config, "0007")
            engine = create_database(self.settings)
            try:
                with engine.begin() as connection:
                    connection.execute(text("""
                        INSERT INTO products (asin, amazon_url, created_at, first_seen_at)
                        VALUES ('B012345678', 'https://www.amazon.pl/dp/B012345678',
                                '2026-01-01', '2026-01-01')
                    """))
                    connection.execute(text("""
                        INSERT INTO refresh_requests (product_id, requested_at, due_at, kind)
                        VALUES (1, '2026-01-01', '2026-01-03', 'regular')
                    """))
                    connection.execute(text("""
                        INSERT INTO price_snapshots (product_id, price, currency, checked_at)
                        VALUES (1, 499.00, 'PLN', '2026-01-02')
                    """))
                command.upgrade(config, "head")
                with engine.connect() as connection:
                    self.assertEqual(connection.execute(text("""
                        SELECT due_at, override_at FROM refresh_requests WHERE product_id = 1
                    """)).one(), ("2026-01-03", None))
                    self.assertEqual(connection.scalar(text("""
                        SELECT price FROM price_snapshots WHERE product_id = 1
                    """)), 499)
                    self.assertEqual(connection.scalar(text("""
                        SELECT COUNT(*) FROM acquisition_attempts
                    """)), 0)
            finally:
                engine.dispose()

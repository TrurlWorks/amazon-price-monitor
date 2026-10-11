import asyncio
import os
from threading import Event
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from backend.config import Settings
from backend.main import create_app
from backend.worker import refresh_due

ROOT = Path(__file__).resolve().parents[1]
CREDENTIALS = {
    "AMAZON_CLIENT_ID": "fixture-private-client",
    "AMAZON_CLIENT_SECRET": "fixture-private-secret",
    "AMAZON_PARTNER_TAG": "fixture-private-partner",
}


class SettingsAPITests(TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.enterContext(patch.dict(os.environ, {
            "MONITOR_DATA_DIR": directory.name,
            "PRODUCT_PROVIDER": "mock",
            "POLL_INTERVAL_SECONDS": "3600",
            "FAILED_RETRY_SECONDS": "90",
            **CREDENTIALS,
        }, clear=True))
        command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
        self.settings = Settings().model_copy(update={"queue_gap_seconds": 0})
        self.app = create_app(self.settings)
        self.client = self.enterContext(TestClient(self.app))

    def test_safe_contract_and_live_counts(self):
        expected = {
            "application_version": "0.8.4",
            "display_mode": "tiles",
            "product_provider": "mock",
            "amazon_credentials_configured": True,
            "poll_interval_seconds": 3600,
            "failed_retry_seconds": 90,
            "status": self.client.get("/api/health").json()["status"],
            "product_count": 0,
            "snapshot_count": 0,
        }
        with self.assertLogs(level="INFO") as logs:
            response = self.client.get("/api/settings")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected)
        for secret in CREDENTIALS.values():
            for output in (
                response.text, repr(response.json()), repr(self.settings),
                str(self.settings), self.settings.model_dump_json(),
                repr(self.settings.model_dump()), "\n".join(logs.output),
                self.client.get("/openapi.json").text,
            ):
                self.assertNotIn(secret, output)

        product_ids = []
        for asin in ("B012345678", "B012345679"):
            response = self.client.post(
                "/api/products", json={"url": f"https://amazon.pl/dp/{asin}"},
            )
            self.assertEqual(response.status_code, 201, response.text)
            product_ids.append(response.json()["id"])
        asyncio.run(refresh_due(
            self.app.state.database, self.app.state.product_provider,
            self.settings, Event(),
        ))
        expected.update(product_count=2, snapshot_count=2)
        self.assertEqual(self.client.get("/api/settings").json(), expected)
        path = f"/api/products/{product_ids[0]}"
        self.assertEqual(self.client.post(path + "/refresh").status_code, 202)
        asyncio.run(refresh_due(
            self.app.state.database, self.app.state.product_provider,
            self.settings, Event(),
        ))
        self.assertEqual(
            self.client.patch(path, json={"is_active": False}).status_code, 200,
        )
        expected["snapshot_count"] = 3
        for _ in range(2):
            self.assertEqual(self.client.get("/api/settings").json(), expected)
        self.assertEqual(self.client.delete(path).status_code, 204)
        expected.update(product_count=1, snapshot_count=1)
        self.assertEqual(self.client.get("/api/settings").json(), expected)

    def test_every_credential_is_required_and_blank_is_absent(self):
        for field in CREDENTIALS:
            for value in (None, "", " \t "):
                with self.subTest(field=field, value=value):
                    environment = dict(os.environ)
                    if value is None:
                        environment.pop(field)
                    else:
                        environment[field] = value
                    with patch.dict(os.environ, environment, clear=True):
                        self.app.state.settings = Settings()
                    response = self.client.get("/api/settings")
                    self.assertEqual(response.status_code, 200)
                    self.assertIs(response.json()["amazon_credentials_configured"], False)
        with patch.dict(os.environ, {}, clear=True):
            self.app.state.settings = Settings()
        response = self.client.get("/api/settings")
        self.assertIs(response.json()["amazon_credentials_configured"], False)
        self.assertEqual(response.json()["poll_interval_seconds"], 21600)
        self.assertEqual(response.json()["failed_retry_seconds"], 60)

    def test_database_errors_are_sanitized(self):
        for target in ("health", "counts"):
            with self.subTest(target=target):
                error = OperationalError(
                    "SELECT 1", {}, Exception(CREDENTIALS["AMAZON_CLIENT_SECRET"]),
                )
                failure = (
                    patch.object(self.app.state.database, "connect", side_effect=error)
                    if target == "health"
                    else patch("backend.api.settings.database_counts", side_effect=error)
                )
                with self.assertLogs(level="INFO") as logs, failure:
                    response = self.client.get("/api/settings")
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json(), {"detail": "Database unavailable"})
                for secret in CREDENTIALS.values():
                    self.assertNotIn(secret, response.text)
                    self.assertNotIn(secret, "\n".join(logs.output))

    def test_put_persists_runtime_intervals_across_app_recreation(self):
        update = {
            "poll_interval_seconds": 7200,
            "failed_retry_seconds": 120,
            "display_mode": "table",
        }
        response = self.client.put("/api/settings", json=update)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["poll_interval_seconds"], 7200)
        self.assertEqual(response.json()["failed_retry_seconds"], 120)
        self.assertEqual(response.json()["display_mode"], "table")

        with TestClient(create_app(Settings())) as recreated:
            persisted = recreated.get("/api/settings")
        self.assertEqual(persisted.status_code, 200)
        self.assertEqual(persisted.json()["poll_interval_seconds"], 7200)
        self.assertEqual(persisted.json()["failed_retry_seconds"], 120)
        self.assertEqual(persisted.json()["display_mode"], "table")

    def test_put_rejects_invalid_or_extra_fields(self):
        valid = {"poll_interval_seconds": 3600, "failed_retry_seconds": 90}
        invalid = (
            {**valid, "poll_interval_seconds": 59},
            {**valid, "failed_retry_seconds": 59},
            {**valid, "poll_interval_seconds": "3600"},
            {**valid, "failed_retry_seconds": 90.0},
            {**valid, "unexpected": 1},
            {**valid, "display_mode": "grid"},
            {"poll_interval_seconds": 3600},
        )
        before = self.client.get("/api/settings").json()
        for payload in invalid:
            with self.subTest(payload=payload):
                response = self.client.put("/api/settings", json=payload)
                self.assertEqual(response.status_code, 422, response.text)
        for method in ("post", "patch", "delete"):
            response = self.client.request(method, "/api/settings", json={})
            self.assertEqual(response.status_code, 405)
        self.assertEqual(self.client.get("/api/settings").json(), before)

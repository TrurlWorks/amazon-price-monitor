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
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.acquisition_queue import claim
from backend.config import Settings
from backend.main import create_app
from backend.mock_provider import MockAmazonProvider
from backend.models import AcquisitionAttempt, PriceSnapshot, QueueState, RefreshRequest, naive_utc
from backend.providers import AmazonBlocked
from backend.worker import refresh_due

ROOT = Path(__file__).resolve().parents[1]


class QueueDiagnosticsTests(TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        environment = patch.dict(os.environ, {"MONITOR_DATA_DIR": directory.name})
        environment.start()
        self.addCleanup(environment.stop)
        command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
        self.settings = Settings(data_dir=Path(directory.name)).model_copy(
            update={"queue_gap_seconds": 0},
        )
        self.app = create_app(self.settings, MockAmazonProvider())
        self.client = self.enterContext(TestClient(self.app))

    def add(self, asin="B012345678"):
        response = self.client.post(
            "/api/products?check_now=false", json={"url": f"https://amazon.pl/dp/{asin}"},
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    def run_at(self, now, provider=None):
        with (
            patch("backend.worker.utcnow", return_value=now),
            patch("backend.services.utcnow", return_value=now),
            patch("backend.acquisition_queue.offset_seconds", return_value=0),
        ):
            asyncio.run(refresh_due(
                self.app.state.database, provider or MockAmazonProvider(),
                self.settings, Event(),
            ))

    def test_one_shot_schedule_survives_reconcile_and_attempt_is_recorded(self):
        product_id = self.add()
        due = datetime.now(UTC).replace(microsecond=0) + timedelta(hours=2)
        response = self.client.patch(
            f"/api/queue/{product_id}/schedule",
            json={"scheduled_at": due.isoformat()},
        )
        self.assertEqual(response.status_code, 204, response.text)
        queue = self.client.get("/api/queue").json()
        self.assertEqual(queue["items"][0]["override_at"], due.replace(tzinfo=None).isoformat())
        self.assertEqual(queue["items"][0]["due_at"], due.replace(tzinfo=None).isoformat())
        self.assertEqual(queue["attempts_total"], 0)
        self.run_at(due - timedelta(minutes=1))
        with Session(self.app.state.database) as session:
            self.assertEqual(session.scalar(select(PriceSnapshot.id)), None)
            self.assertEqual(session.get(RefreshRequest, product_id).due_at, naive_utc(due))
        self.run_at(due)
        queue = self.client.get("/api/queue").json()
        self.assertEqual(queue["recent_attempts"][0]["outcome"], "success")
        self.assertEqual(queue["recent_attempts"][0]["kind"], "manual")
        self.assertEqual(queue["items"][0]["last_outcome"], "success")
        with Session(self.app.state.database) as session:
            request = session.get(RefreshRequest, product_id)
            self.assertIsNone(request.override_at)
            self.assertEqual(request.kind, "regular")
            self.assertGreater(request.due_at, naive_utc(due))

    def test_schedule_rejects_invalid_time_and_paused_product(self):
        product_id = self.add()
        endpoint = f"/api/queue/{product_id}/schedule"
        for date in ("2026-01-01T12:00:00", datetime.now(UTC).isoformat()):
            response = self.client.patch(endpoint, json={"scheduled_at": date})
            self.assertEqual(response.status_code, 422, response.text)
        future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        self.assertEqual(self.client.patch(
            "/api/queue/999/schedule", json={"scheduled_at": future},
        ).status_code, 404)
        self.assertEqual(self.client.patch(
            f"/api/products/{product_id}", json={"is_active": False},
        ).status_code, 200)
        self.assertEqual(self.client.patch(
            endpoint, json={"scheduled_at": future},
        ).status_code, 409)
        self.assertIsNone(self.client.get("/api/queue").json()["items"][0]["due_at"])

    def test_blocked_outcome_is_visible_without_raw_provider_message(self):
        product_id = self.add()

        class Blocked(MockAmazonProvider):
            async def get_offer(self, asin):
                raise AmazonBlocked("private fixture detail")

        self.run_at(datetime.now(UTC) + timedelta(minutes=1), Blocked())
        response = self.client.get("/api/queue?limit=1&offset=0")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["recent_attempts"][0]["outcome"], "blocked")
        self.assertEqual(response.json()["items"][0]["last_outcome"], "blocked")
        self.assertNotIn("private fixture detail", response.text)
        self.assertEqual(self.client.get("/api/queue?limit=101").status_code, 422)
        self.assertEqual(self.client.get(f"/api/products/{product_id}/history").json()["snapshots"], [])

    def test_stale_claim_is_marked_interrupted_before_new_attempt(self):
        product_id = self.add()
        start = datetime.now(UTC).replace(microsecond=0) + timedelta(minutes=1)
        with Session(self.app.state.database) as session:
            self.assertEqual(claim(session, self.settings, naive_utc(start))[0], product_id)
        with Session(self.app.state.database) as session:
            self.assertEqual(claim(
                session, self.settings, naive_utc(start + timedelta(minutes=6)),
            )[0], product_id)
            attempts = list(session.scalars(select(AcquisitionAttempt).order_by(AcquisitionAttempt.id)))
            self.assertEqual([item.outcome for item in attempts], ["interrupted", "checking"])

    def test_planned_start_accounts_for_global_spacing_and_backlog(self):
        for asin in ("B012345678", "B012345679", "B012345680"):
            self.add(asin)
        self.app.state.settings = self.settings.model_copy(update={"queue_gap_seconds": 180})
        queue = self.client.get("/api/queue").json()
        self.assertEqual(len(queue["items"]), 3)
        planned = [datetime.fromisoformat(item["planned_at"]) for item in queue["items"]]
        self.assertGreaterEqual(planned[0], datetime.fromisoformat(queue["as_of"]))
        self.assertEqual(planned[1] - planned[0], timedelta(seconds=180))
        self.assertEqual(planned[2] - planned[1], timedelta(seconds=180))

    def test_refresh_now_reads_immediately_and_does_not_add_a_queue_entry(self):
        product_id = self.add()
        self.app.state.settings = self.settings.model_copy(update={"queue_gap_seconds": 3600})
        response = self.client.post(f"/api/products/{product_id}/refresh-now")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["queue_state"], "regular")
        with Session(self.app.state.database) as session:
            self.assertEqual(session.query(RefreshRequest).count(), 1)
            self.assertEqual(session.query(PriceSnapshot).count(), 1)
            self.assertEqual(session.get(QueueState, 1).last_started_at is not None, True)
        queue = self.client.get("/api/queue").json()
        self.assertEqual(queue["attempts_total"], 1)
        self.assertEqual(queue["recent_attempts"][0]["outcome"], "success")
        # A manually paused product has no queue slot but can still be checked.
        self.assertEqual(self.client.patch(
            f"/api/products/{product_id}", json={"is_active": False},
        ).status_code, 200)
        response = self.client.post(f"/api/products/{product_id}/refresh-now")
        self.assertEqual(response.status_code, 200, response.text)
        with Session(self.app.state.database) as session:
            self.assertEqual(session.query(RefreshRequest).count(), 0)
            self.assertEqual(session.query(PriceSnapshot).count(), 2)

    def test_refresh_now_failure_preserves_queued_term_and_records_result(self):
        product_id = self.add()
        with Session(self.app.state.database) as session:
            original_due = session.get(RefreshRequest, product_id).due_at
        class Blocked(MockAmazonProvider):
            async def get_offer(self, asin):
                raise AmazonBlocked("private fixture detail")

        self.app.state.product_provider = Blocked()
        response = self.client.post(f"/api/products/{product_id}/refresh-now")
        self.assertEqual(response.status_code, 503, response.text)
        self.assertNotIn("private fixture detail", response.text)
        with Session(self.app.state.database) as session:
            request = session.get(RefreshRequest, product_id)
            self.assertEqual(request.due_at, original_due)
            self.assertIsNone(request.started_at)
            self.assertEqual(session.query(PriceSnapshot).count(), 0)
        queue = self.client.get("/api/queue").json()
        self.assertEqual(queue["recent_attempts"][0]["outcome"], "blocked")

    def test_refresh_now_rejects_a_product_already_being_checked(self):
        product_id = self.add()
        with Session(self.app.state.database) as session:
            session.get(RefreshRequest, product_id).started_at = naive_utc(datetime.now(UTC))
            session.commit()
        response = self.client.post(f"/api/products/{product_id}/refresh-now")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), {"detail": "refresh_in_progress"})
        with Session(self.app.state.database) as session:
            self.assertEqual(session.query(AcquisitionAttempt).count(), 0)

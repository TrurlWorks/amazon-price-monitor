import os
from unittest import TestCase
from unittest.mock import patch

from pydantic import ValidationError

from backend.config import Settings


class SettingsTests(TestCase):
    def test_poll_interval_default(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(Settings().poll_interval_seconds, 21600)
            self.assertEqual(Settings().failed_retry_seconds, 60)
            self.assertEqual(Settings().queue_gap_seconds, 180)

    def test_queue_gap_requires_at_least_one_minute(self):
        for value in ("0", "59"):
            with self.subTest(value=value):
                with patch.dict(os.environ, {"QUEUE_GAP_SECONDS": value}, clear=True):
                    with self.assertRaises(ValidationError):
                        Settings()

    def test_poll_interval_environment(self):
        for value in ("60", "3600"):
            with self.subTest(value=value):
                with patch.dict(os.environ, {"POLL_INTERVAL_SECONDS": value}, clear=True):
                    self.assertEqual(Settings().poll_interval_seconds, int(value))

    def test_invalid_poll_interval(self):
        for value in ("59", "0", "-1", "60.5", "invalid", ""):
            with self.subTest(value=value):
                with patch.dict(os.environ, {"POLL_INTERVAL_SECONDS": value}, clear=True):
                    with self.assertRaises(ValidationError):
                        Settings()

    def test_failed_retry_environment(self):
        for value in ("60", "120"):
            with self.subTest(value=value):
                with patch.dict(os.environ, {"FAILED_RETRY_SECONDS": value}, clear=True):
                    self.assertEqual(Settings().failed_retry_seconds, int(value))

    def test_invalid_failed_retry(self):
        for value in ("59", "1", "0", "-1", "60.5", "invalid", ""):
            with self.subTest(value=value):
                with patch.dict(os.environ, {"FAILED_RETRY_SECONDS": value}, clear=True):
                    with self.assertRaises(ValidationError):
                        Settings()

"""Single worker scheduling checks from persisted attempt times."""

import asyncio
import fcntl
import logging
import signal
import time
from threading import Event

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.acquisition_queue import claim, finish, remove
from backend.config import Settings
from backend.database import create_database
from backend.models import Product, naive_utc, utcnow
from backend.providers import AmazonBlocked, ProductNotFound, ProviderError
from backend.services import MissingProduct, ProductService, create_provider


async def refresh_due(engine, provider, settings, stop):
    while not stop.is_set():
        now = naive_utc(utcnow())
        with Session(engine) as session:
            queued = claim(session, settings, now)
        if queued is None:
            return
        product_id, kind = queued
        succeeded = False
        blocked = False
        outcome = "error"
        with Session(engine, expire_on_commit=False) as session:
            product = session.get(Product, product_id)
            if product is None or (
                kind != "manual" and not product.is_active
                and product.pause_reason != "automatic"
            ):
                remove(session, product_id)
                session.commit()
                continue
            try:
                await ProductService(session, provider, settings).refresh(
                    product_id, automated=kind != "manual",
                )
                succeeded = True
                outcome = "success"
            except (ProviderError, MissingProduct) as error:
                blocked = isinstance(error, AmazonBlocked)
                outcome = "blocked" if blocked else "not_found" if isinstance(error, ProductNotFound) else "error"
                logging.warning("Scheduled refresh failed for product %s", product_id)
            except Exception:
                logging.exception("Unexpected queued refresh failure for product %s", product_id)
        with Session(engine) as session:
            finish(
                session, settings, product_id, kind, naive_utc(utcnow()),
                succeeded=succeeded, blocked=blocked, outcome=outcome,
            )


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    stop = Event()
    heartbeat = settings.data_dir / "worker.heartbeat"

    def shutdown(_signum, _frame):
        stop.set()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    # The OS releases this lock on process exit, including an abrupt termination.
    with (settings.data_dir / "worker.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("A worker already owns this data directory") from None
        engine = create_database(settings)
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            provider = create_provider(settings)
            logging.info("Worker ready")
            while not stop.is_set():
                with engine.connect() as connection:
                    connection.execute(text("SELECT 1"))
                heartbeat.touch()
                asyncio.run(refresh_due(engine, provider, settings, stop))
                stop.wait(5)
        finally:
            try:
                heartbeat.unlink(missing_ok=True)
            finally:
                engine.dispose()


def healthy() -> bool:
    try:
        age = time.time() - (Settings().data_dir / "worker.heartbeat").stat().st_mtime
    except OSError:
        return False
    return 0 <= age < 20


if __name__ == "__main__":
    main()

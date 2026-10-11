"""Persistent, coalesced acquisition slots; only the worker claims network work."""

import hashlib
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from backend.models import AcquisitionAttempt, Product, QueueState, RefreshRequest
from backend.repositories import effective_intervals

RECOVERY_FIRST = timedelta(hours=12)
RECOVERY_LATER = timedelta(hours=24)
CHALLENGE_WINDOW = timedelta(hours=1)
GLOBAL_COOLDOWN = timedelta(hours=2)
PROBE_COOLDOWN = timedelta(hours=4)
CLAIM_LEASE = timedelta(minutes=5)


def offset_seconds(asin: str, limit: int) -> int:
    if limit <= 0:
        return 0
    number = int.from_bytes(hashlib.sha256(asin.encode("ascii")).digest()[:8])
    return number % (limit + 1)


def enqueue(
    session: Session, product: Product, *, kind: str, due_at: datetime,
) -> RefreshRequest:
    """Keep one slot per product; repeated clicks cannot create more traffic."""
    request = session.get(RefreshRequest, product.id)
    if request is None:
        request = RefreshRequest(
            product_id=product.id, requested_at=due_at, due_at=due_at,
            kind=kind,
        )
        session.add(request)
    elif request.started_at is None and kind == "manual":
        request.kind = "manual"
        request.due_at = min(request.due_at, due_at)
        request.override_at = None
        request.requested_at = due_at
    session.flush()
    return request


def remove(session: Session, product_id: int) -> None:
    request = session.get(RefreshRequest, product_id)
    if request is not None:
        session.delete(request)
        session.flush()


def _queue_state(session: Session) -> QueueState:
    state = session.get(QueueState, 1)
    if state is None:
        state = QueueState(id=1)
        session.add(state)
        session.flush()
    return state


def reconcile(session: Session, settings, now: datetime) -> None:
    """Supply slots for existing products and recover orphaned work."""
    intervals = effective_intervals(session, settings)
    products = session.scalars(
        select(Product).outerjoin(RefreshRequest, Product.id == RefreshRequest.product_id)
        .where(RefreshRequest.product_id.is_(None))
    )
    for product in products:
        if not product.is_active and product.pause_reason != "automatic":
            continue
        if product.pause_reason == "automatic":
            due = now + RECOVERY_FIRST
            kind = "recovery"
        elif product.consecutive_failures > 0:
            due = product.last_checked_at + timedelta(
                seconds=intervals.failed_retry_seconds,
            ) if product.last_checked_at else now
            kind = "retry"
        elif product.last_checked_at is None:
            due = now
            kind = "regular"
        else:
            due = product.last_checked_at + timedelta(seconds=intervals.poll_interval_seconds)
            kind = "regular"
        enqueue(session, product, kind=kind, due_at=due)

    for request, product in session.execute(
        select(RefreshRequest, Product)
        .join(Product, Product.id == RefreshRequest.product_id)
        .where(RefreshRequest.kind == "regular", RefreshRequest.started_at.is_(None))
    ):
        if product.last_checked_at is not None and request.override_at is None:
            interval = intervals.poll_interval_seconds
            jitter = offset_seconds(product.asin, min(interval // 10, 900))
            request.due_at = product.last_checked_at + timedelta(seconds=interval + jitter)

    for request in session.scalars(select(RefreshRequest).where(
        RefreshRequest.started_at.is_not(None),
        RefreshRequest.started_at <= now - CLAIM_LEASE,
    )):
        attempt = session.scalar(select(AcquisitionAttempt).where(
            AcquisitionAttempt.product_id == request.product_id,
            AcquisitionAttempt.outcome == "checking",
        ).order_by(AcquisitionAttempt.id.desc()))
        if attempt is not None:
            attempt.finished_at = now
            attempt.outcome = "interrupted"
        request.started_at = None


def claim(session: Session, settings, now: datetime) -> tuple[int, str] | None:
    """Reserve one global start slot before any network request."""
    state = _queue_state(session)
    reconcile(session, settings, now)
    if state.cooldown_until is not None and now < state.cooldown_until:
        session.commit()
        return None
    if state.last_started_at is not None and now < (
        state.last_started_at + timedelta(seconds=settings.queue_gap_seconds)
    ):
        session.commit()
        return None
    due = list(session.scalars(
        select(RefreshRequest).where(
            RefreshRequest.due_at <= now,
            RefreshRequest.started_at.is_(None),
        ).order_by(RefreshRequest.due_at, RefreshRequest.product_id)
    ))
    if not due:
        session.commit()
        return None
    manual = next((item for item in due if item.kind == "manual"), None)
    other = next((item for item in due if item.kind != "manual"), None)
    request = manual if manual and (state.manual_streak < 2 or other is None) else other
    if request is None:
        request = manual
    claimed = session.execute(
        update(RefreshRequest).where(
            RefreshRequest.product_id == request.product_id,
            RefreshRequest.started_at.is_(None),
        ).values(started_at=now)
    )
    if claimed.rowcount != 1:
        session.commit()
        return None
    state.manual_streak = state.manual_streak + 1 if request.kind == "manual" else 0
    state.last_started_at = now
    session.add(AcquisitionAttempt(
        product_id=request.product_id, kind=request.kind,
        started_at=now, outcome="checking",
    ))
    result = request.product_id, request.kind
    session.commit()
    return result


def begin_direct(session: Session, product_id: int, now: datetime) -> bool:
    """Mark an immediate API read without enqueuing another request."""
    request = session.get(RefreshRequest, product_id)
    if request is not None:
        if request.started_at is not None:
            return False
        claimed = session.execute(
            update(RefreshRequest).where(
                RefreshRequest.product_id == product_id,
                RefreshRequest.started_at.is_(None),
            ).values(started_at=now)
        )
        if claimed.rowcount != 1:
            session.rollback()
            return False
    state = _queue_state(session)
    state.last_started_at = now
    session.add(AcquisitionAttempt(
        product_id=product_id, kind="manual", started_at=now, outcome="checking",
    ))
    session.commit()
    return True


def finish(
    session: Session, settings, product_id: int, kind: str, now: datetime,
    *, succeeded: bool, blocked: bool, outcome: str, direct: bool = False,
) -> None:
    """Schedule one next observation without replaying missed cycles."""
    request = session.get(RefreshRequest, product_id)
    product = session.get(Product, product_id)
    attempt = session.scalar(select(AcquisitionAttempt).where(
        AcquisitionAttempt.product_id == product_id,
        AcquisitionAttempt.outcome == "checking",
    ).order_by(AcquisitionAttempt.id.desc()))
    if attempt is not None:
        attempt.finished_at = now
        attempt.outcome = outcome
    state = _queue_state(session)
    if blocked:
        if state.cooldown_until is not None and now >= state.cooldown_until:
            state.cooldown_until = now + PROBE_COOLDOWN
        elif (
            state.last_challenge_at is not None
            and now - state.last_challenge_at <= CHALLENGE_WINDOW
            and state.last_challenge_product_id != product_id
        ):
            state.cooldown_until = now + GLOBAL_COOLDOWN
        state.last_challenge_at = now
        state.last_challenge_product_id = product_id
        state.challenge_count += 1
    elif succeeded:
        state.challenge_count = 0
        state.last_challenge_at = None
        state.last_challenge_product_id = None
        state.cooldown_until = None

    if request is None or product is None:
        session.commit()
        return

    request.started_at = None
    if direct and not succeeded:
        session.commit()
        return
    request.override_at = None
    if not product.is_active and product.pause_reason != "automatic":
        session.delete(request)
    elif succeeded:
        interval = effective_intervals(session, settings).poll_interval_seconds
        jitter = offset_seconds(product.asin, min(interval // 10, 900))
        request.due_at = now + timedelta(seconds=interval + jitter)
        request.kind = "regular"
    elif product.pause_reason == "automatic":
        request.due_at = now + (RECOVERY_LATER if kind == "recovery" else RECOVERY_FIRST)
        request.kind = "recovery"
    else:
        interval = effective_intervals(session, settings).failed_retry_seconds
        count = max(product.automatic_failures, 1)
        delay = interval * min(2 ** (count - 1), 4)
        jitter = offset_seconds(product.asin, min(delay // 10, 300))
        request.due_at = now + timedelta(seconds=delay + jitter)
        request.kind = "retry"
    session.commit()

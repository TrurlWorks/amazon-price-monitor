"""Read-only queue diagnostics and explicit one-shot scheduling."""

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.acquisition_queue import reconcile
from backend.models import (
    AcquisitionAttempt, Product, QueueState, RefreshRequest, naive_utc, utcnow,
)


class ScheduleConflict(Exception):
    pass


class InvalidSchedule(Exception):
    pass


class UnknownProduct(Exception):
    pass


def planned_starts(
    requests: list[RefreshRequest], available_at: datetime,
    gap_seconds: int, manual_streak: int,
) -> dict[int, datetime]:
    """Project the current queue with the same priority rule as the worker."""
    remaining = sorted(
        (request for request in requests if request.started_at is None),
        key=lambda request: (request.due_at, request.product_id),
    )
    planned = {}
    cursor = available_at
    while remaining:
        if remaining[0].due_at > cursor:
            cursor = remaining[0].due_at
        due = [request for request in remaining if request.due_at <= cursor]
        manual = next((request for request in due if request.kind == "manual"), None)
        other = next((request for request in due if request.kind != "manual"), None)
        selected = manual if manual and (manual_streak < 2 or other is None) else other
        if selected is None:
            selected = manual
        planned[selected.product_id] = cursor
        manual_streak = manual_streak + 1 if selected.kind == "manual" else 0
        remaining.remove(selected)
        cursor += timedelta(seconds=gap_seconds)
    return planned


def diagnostics(session: Session, settings, *, limit: int, offset: int) -> dict:
    now = naive_utc(utcnow())
    state = session.get(QueueState, 1)
    available_at = now
    if state is not None:
        if state.cooldown_until and state.cooldown_until > available_at:
            available_at = state.cooldown_until
        if state.last_started_at:
            gap_end = state.last_started_at + timedelta(seconds=settings.queue_gap_seconds)
            if gap_end > available_at:
                available_at = gap_end

    latest_ids = select(func.max(AcquisitionAttempt.id).label("id")).group_by(
        AcquisitionAttempt.product_id,
    ).subquery()
    latest = {
        attempt.product_id: attempt
        for attempt in session.scalars(
            select(AcquisitionAttempt).join(latest_ids, AcquisitionAttempt.id == latest_ids.c.id)
        )
    }
    rows = session.execute(
        select(Product, RefreshRequest).outerjoin(
            RefreshRequest, Product.id == RefreshRequest.product_id,
        )
    ).all()
    planned = planned_starts(
        [request for _, request in rows if request is not None],
        available_at, settings.queue_gap_seconds,
        state.manual_streak if state else 0,
    )
    items = []
    for product, request in rows:
        last = latest.get(product.id)
        items.append({
            "product_id": product.id, "asin": product.asin, "title": product.title,
            "image_url": product.image_url,
            "is_active": product.is_active, "pause_reason": product.pause_reason,
            "kind": request.kind if request else None,
            "due_at": request.due_at if request else None,
            "planned_at": planned.get(product.id),
            "override_at": request.override_at if request else None,
            "started_at": request.started_at if request else None,
            "last_checked_at": product.last_checked_at,
            "last_attempt_at": last.started_at if last else None,
            "last_outcome": last.outcome if last else None,
        })
    items.sort(key=lambda item: (
        item["planned_at"] is None, item["planned_at"] or now, item["asin"],
    ))
    total = session.scalar(select(func.count()).select_from(AcquisitionAttempt)) or 0
    attempts = session.execute(
        select(AcquisitionAttempt, Product)
        .join(Product, Product.id == AcquisitionAttempt.product_id)
        .order_by(AcquisitionAttempt.id.desc()).limit(limit).offset(offset)
    ).all()
    return {
        "as_of": now,
        "global_available_at": available_at,
        "cooldown_until": state.cooldown_until if state else None,
        "items": items,
        "recent_attempts": [{
            "id": attempt.id, "product_id": product.id, "asin": product.asin,
            "title": product.title, "kind": attempt.kind,
            "started_at": attempt.started_at, "finished_at": attempt.finished_at,
            "outcome": attempt.outcome,
        } for attempt, product in attempts],
        "attempts_total": total,
    }


def schedule_product(session: Session, settings, product_id: int, scheduled_at) -> None:
    now = naive_utc(utcnow())
    due = naive_utc(scheduled_at)
    if not now + timedelta(minutes=1) <= due <= now + timedelta(days=365):
        raise InvalidSchedule()
    product = session.get(Product, product_id)
    if product is None:
        raise UnknownProduct()
    if not product.is_active and product.pause_reason != "automatic":
        raise ScheduleConflict()
    request = session.get(RefreshRequest, product_id)
    if request is None:
        reconcile(session, settings, now)
        request = session.get(RefreshRequest, product_id)
    if request is None or request.started_at is not None:
        raise ScheduleConflict()
    request.due_at = due
    request.override_at = due
    session.commit()

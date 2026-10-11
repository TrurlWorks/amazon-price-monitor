"""Queue status and one-shot product scheduling for the diagnostics page."""

from datetime import datetime
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import AwareDatetime, BaseModel, ConfigDict
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.queue_diagnostics import (
    InvalidSchedule, ScheduleConflict, UnknownProduct, diagnostics, schedule_product,
)

router = APIRouter(prefix="/queue")


class QueueItem(BaseModel):
    product_id: int
    asin: str
    title: str | None
    image_url: str | None
    is_active: bool
    pause_reason: str | None
    kind: str | None
    due_at: datetime | None
    planned_at: datetime | None
    override_at: datetime | None
    started_at: datetime | None
    last_checked_at: datetime | None
    last_attempt_at: datetime | None
    last_outcome: str | None


class AttemptItem(BaseModel):
    id: int
    product_id: int
    asin: str
    title: str | None
    kind: str
    started_at: datetime
    finished_at: datetime | None
    outcome: str


class QueueResponse(BaseModel):
    as_of: datetime
    global_available_at: datetime
    cooldown_until: datetime | None
    items: list[QueueItem]
    recent_attempts: list[AttemptItem]
    attempts_total: int


class ScheduleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scheduled_at: AwareDatetime


@router.get("", response_model=QueueResponse)
def queue_status(request: Request, limit: int = Query(20, ge=1, le=100),
                 offset: int = Query(0, ge=0)):
    try:
        with Session(request.app.state.database) as session:
            return diagnostics(session, request.app.state.settings, limit=limit, offset=offset)
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="Database unavailable") from None


@router.patch("/{product_id}/schedule", status_code=204)
async def update_schedule(product_id: int, payload: ScheduleUpdate, request: Request):
    if product_id <= 0:
        raise HTTPException(status_code=422, detail="Invalid product id")
    try:
        async with request.app.state.product_lock:
            with Session(request.app.state.database) as session:
                schedule_product(
                    session, request.app.state.settings, product_id, payload.scheduled_at,
                )
    except UnknownProduct:
        raise HTTPException(status_code=404, detail="product_not_found") from None
    except ScheduleConflict:
        raise HTTPException(status_code=409, detail="schedule_conflict") from None
    except InvalidSchedule:
        raise HTTPException(status_code=422, detail="invalid_schedule") from None
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="Database unavailable") from None

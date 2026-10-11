"""Public status and editable runtime intervals with an explicit allowlist."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.api.health import health
from backend.repositories import (
    database_counts, display_mode, effective_intervals, set_runtime_intervals,
)
from backend.version import APP_VERSION

router = APIRouter()


class SettingsResponse(BaseModel):
    application_version: str
    display_mode: Literal["tiles", "table"]
    product_provider: str
    amazon_credentials_configured: bool
    poll_interval_seconds: int
    failed_retry_seconds: int
    status: Literal["ok"]
    product_count: int
    snapshot_count: int


class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    poll_interval_seconds: int = Field(ge=60, strict=True)
    failed_retry_seconds: int = Field(ge=60, strict=True)
    display_mode: Literal["tiles", "table"] | None = None


@router.get("/settings", response_model=SettingsResponse)
def settings_status(request: Request) -> SettingsResponse:
    application_health = health(request)
    settings = request.app.state.settings
    try:
        with Session(request.app.state.database) as session:
            product_count, snapshot_count = database_counts(session)
            intervals = effective_intervals(session, settings)
            selected_display_mode = display_mode(session)
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="Database unavailable") from None

    credentials_configured = all(
        bool(value.get_secret_value().strip())
        for value in (
            settings.amazon_client_id,
            settings.amazon_client_secret,
            settings.amazon_partner_tag,
        )
    )
    return SettingsResponse(
        application_version=APP_VERSION,
        display_mode=selected_display_mode,
        product_provider=settings.product_provider,
        amazon_credentials_configured=credentials_configured,
        poll_interval_seconds=intervals.poll_interval_seconds,
        failed_retry_seconds=intervals.failed_retry_seconds,
        status=application_health.status,
        product_count=product_count,
        snapshot_count=snapshot_count,
    )


@router.put("/settings", response_model=SettingsResponse)
def update_settings(payload: SettingsUpdate, request: Request) -> SettingsResponse:
    try:
        with Session(request.app.state.database) as session:
            set_runtime_intervals(
                session,
                poll_interval_seconds=payload.poll_interval_seconds,
                failed_retry_seconds=payload.failed_retry_seconds,
                display_mode=payload.display_mode,
            )
            session.commit()
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="Database unavailable") from None
    return settings_status(request)

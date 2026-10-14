"""HTTP contracts and dependency wiring; policy lives in ProductService."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, StrictBool, StrictStr
from sqlalchemy.orm import Session

from backend.amazon_urls import InvalidProductURL
from backend.models import ProductStatus
from backend.providers import (
    AmazonBlocked,
    ProductNotFound,
    ProviderError,
    ProviderUnavailable,
    TransientProviderError,
)
from backend.repositories import PriceStats
from backend.services import (
    DuplicateProduct,
    InvalidCurrency,
    MissingProduct,
    ProductService,
    RefreshInProgress,
)

router = APIRouter(prefix="/products")


class AddProduct(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: StrictStr


class UpdateProduct(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_active: StrictBool


class ProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    asin: str
    amazon_url: str
    title: str | None
    image_url: str | None
    created_at: datetime
    first_seen_at: datetime
    last_checked_at: datetime | None
    status: ProductStatus
    is_active: bool
    pause_reason: str | None
    next_check_at: datetime | None
    queue_state: str | None
    consecutive_failures: int
    automatic_failures: int
    consecutive_not_found: int


class SnapshotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    product_id: int
    price: Decimal | None
    currency: str
    seller: str | None
    availability: str | None
    is_buy_box: bool | None
    checked_at: datetime


class HistoryResponse(BaseModel):
    product_id: int
    currency: str
    snapshots: list[SnapshotResponse]
    stats: PriceStats


def get_provider(request: Request):
    return request.app.state.product_provider


async def get_service(request: Request, provider=Depends(get_provider)):
    # Serialize API operations, including observation counters and failure updates.
    async with request.app.state.product_lock:
        with Session(request.app.state.database, expire_on_commit=False) as session:
            yield ProductService(session, provider, request.app.state.settings)


Service = Annotated[ProductService, Depends(get_service)]
ProductID = Annotated[int, Path(gt=0)]


@router.post("", response_model=ProductResponse, status_code=201)
async def add_product(body: AddProduct, service: Service, check_now: bool = True):
    return await service.add_now(body.url) if check_now else service.add_queued(body.url)


@router.get("", response_model=list[ProductResponse])
async def list_products(service: Service):
    return service.list()


@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(product_id: ProductID, service: Service):
    return service.get(product_id)


@router.patch("/{product_id}", response_model=ProductResponse)
async def update_product(product_id: ProductID, body: UpdateProduct, service: Service):
    return service.set_active(product_id, body.is_active)


@router.delete("/{product_id}", status_code=204)
async def delete_product(product_id: ProductID, service: Service):
    service.delete(product_id)
    return Response(status_code=204)


@router.post("/{product_id}/refresh", response_model=ProductResponse, status_code=202)
async def refresh_product(product_id: ProductID, service: Service):
    return service.queue_refresh(product_id)


@router.post("/{product_id}/refresh-now", response_model=ProductResponse)
async def refresh_product_now(product_id: ProductID, service: Service):
    return await service.refresh_now(product_id)


@router.get("/{product_id}/history", response_model=HistoryResponse)
async def product_history(product_id: ProductID, service: Service, currency: str = "PLN"):
    return service.history(product_id, currency)


async def domain_error(_request: Request, exc: Exception):
    errors = {
        InvalidProductURL: (422, "invalid_product_url"),
        InvalidCurrency: (422, "invalid_currency"),
        MissingProduct: (404, "product_not_found"),
        DuplicateProduct: (409, "duplicate_asin"),
        RefreshInProgress: (409, "refresh_in_progress"),
        ProductNotFound: (404, "provider_product_not_found"),
        ProviderUnavailable: (503, "provider_unavailable"),
        TransientProviderError: (503, "provider_temporary_failure"),
        AmazonBlocked: (503, "provider_temporary_failure"),
    }
    status, code = errors.get(type(exc), (503, "provider_failure"))
    return JSONResponse(status_code=status, content={"detail": code})


DOMAIN_ERRORS = (InvalidProductURL, InvalidCurrency, MissingProduct, DuplicateProduct, RefreshInProgress, ProviderError)

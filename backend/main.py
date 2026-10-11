import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.api.health import router
from backend.api.products import DOMAIN_ERRORS, domain_error, router as products_router
from backend.api.queue import router as queue_router
from backend.api.settings import router as settings_router
from backend.config import Settings
from backend.database import create_database
from backend.providers import ProductProvider
from backend.services import create_provider


def create_app(settings: Settings | None = None, provider: ProductProvider | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = create_database(settings)
        app.state.database = engine
        app.state.settings = settings
        app.state.product_provider = provider if provider is not None else create_provider(settings)
        app.state.product_lock = asyncio.Lock()
        try:
            yield
        finally:
            engine.dispose()

    app = FastAPI(title="Amazon.pl Price Monitor", lifespan=lifespan)
    app.include_router(router, prefix="/api")
    app.include_router(products_router, prefix="/api")
    app.include_router(queue_router, prefix="/api")
    app.include_router(settings_router, prefix="/api")
    for exception in DOMAIN_ERRORS:
        app.add_exception_handler(exception, domain_error)
    return app

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.db.session import init_db
from app.services.processing_service import ProcessingService
from app.services.storage_service import StorageService

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(log_level=settings.log_level, log_json=settings.log_json)
    init_db()
    StorageService().ensure_directories()
    ProcessingService().ensure_directories()
    log.info("application_startup", app=settings.app_name)
    yield
    log.info("application_shutdown")


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.include_router(api_router, prefix="/api/v1")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

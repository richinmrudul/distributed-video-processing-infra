from contextlib import asynccontextmanager

from fastapi import FastAPI
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import Response

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.core.prometheus_middleware import PrometheusMiddleware
from app.core.tracing import configure_tracing, instrument_fastapi
from app.services.processing_service import ProcessingService
from app.services.storage_service import StorageService

log = get_logger(__name__)


def parse_cors_allowed_origins(value: str) -> list[str]:
    return [origin.strip() for origin in value.split(",") if origin.strip()]


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(log_level=settings.log_level, log_json=settings.log_json)
    StorageService().ensure_directories()
    ProcessingService().ensure_directories()
    log.info("application_startup", app=settings.app_name)
    yield
    log.info("application_shutdown")


configure_tracing(settings.otel_service_name)

app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
    openapi_tags=[
        {"name": "Health", "description": "Public service health checks."},
        {"name": "Videos", "description": "Public client video upload, status, and asset endpoints."},
        {"name": "Queue", "description": "Public queue health endpoint."},
        {"name": "Storage", "description": "Public storage health endpoint."},
        {"name": "Admin Jobs", "description": "Protected operator endpoints requiring X-Admin-API-Key."},
    ],
)
app.add_middleware(PrometheusMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=parse_cors_allowed_origins(settings.cors_allowed_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
app.include_router(api_router, prefix="/api/v1")
instrument_fastapi(app)


@app.get("/health", tags=["Health"], summary="Get API health", description="Public endpoint. Returns API liveness.")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics")
def metrics() -> Response:
    """Prometheus scrape endpoint (root-level, not under /api/v1)."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

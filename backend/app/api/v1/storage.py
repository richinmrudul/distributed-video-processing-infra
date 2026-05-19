from fastapi import APIRouter, status

from app.core.config import settings
from app.core.logging import get_logger
from app.schemas.storage import StorageHealthResponse
from app.services.object_storage_service import ObjectStorageError, ObjectStorageService

router = APIRouter()
log = get_logger(__name__)


def _expected_buckets() -> list[str]:
    return [
        settings.raw_video_bucket,
        settings.processed_video_bucket,
        settings.thumbnail_bucket,
    ]


def _is_configured() -> bool:
    ep = str(settings.object_storage_endpoint or "").strip()
    ak = str(settings.object_storage_access_key or "").strip()
    sk = str(settings.object_storage_secret_key or "").strip()
    return bool(ep and ak and sk)


def _response(
    *,
    backend_configured: bool,
    connected: bool,
    buckets: list[str],
    error: str | None,
) -> StorageHealthResponse:
    """Always return a model matching StorageHealthResponse (HTTP 200 from route)."""
    secure = bool(settings.object_storage_secure)
    return StorageHealthResponse(
        backend_configured=backend_configured,
        storage_backend=str(settings.storage_backend or "local"),
        endpoint=str(settings.object_storage_endpoint or ""),
        public_endpoint=str(settings.object_storage_public_endpoint or ""),
        secure=secure,
        expected_buckets=_expected_buckets(),
        buckets=buckets,
        connected=connected,
        error=error,
    )


@router.get(
    "/health",
    response_model=StorageHealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Get storage health",
    description="Public endpoint. Returns object storage configuration and bucket connectivity status.",
)
def storage_health() -> StorageHealthResponse:
    """Never raises: always JSON 200 for ops probes (MinIO down, boto errors, bad config)."""
    try:
        return _storage_health_inner()
    except Exception as exc:
        log.warning("storage_health_unexpected_failure", error=str(exc))
        return _response(
            backend_configured=_is_configured(),
            connected=False,
            buckets=[],
            error="storage health failed unexpectedly",
        )


def _storage_health_inner() -> StorageHealthResponse:
    configured = _is_configured()
    if not configured:
        return _response(
            backend_configured=False,
            connected=False,
            buckets=[],
            error="object storage endpoint or credentials are empty",
        )

    try:
        svc = ObjectStorageService()
    except Exception as exc:
        log.warning("object_storage_client_init_failed", error=str(exc))
        return _response(
            backend_configured=True,
            connected=False,
            buckets=[],
            error=f"object storage client could not be created: {exc}",
        )

    try:
        if not svc.check_connection():
            return _response(
                backend_configured=True,
                connected=False,
                buckets=[],
                error="could not reach object storage (list_buckets failed)",
            )
    except Exception as exc:
        log.warning("object_storage_check_connection_raised", error=str(exc))
        return _response(
            backend_configured=True,
            connected=False,
            buckets=[],
            error=f"connection check error: {exc}",
        )

    try:
        names = svc.list_buckets()
    except ObjectStorageError as exc:
        return _response(
            backend_configured=True,
            connected=False,
            buckets=[],
            error=str(exc),
        )
    except Exception as exc:
        log.warning("object_storage_list_buckets_unexpected", error=str(exc))
        return _response(
            backend_configured=True,
            connected=False,
            buckets=[],
            error=f"list_buckets error: {exc}",
        )

    expected = _expected_buckets()
    missing = [b for b in expected if b not in names]
    if missing:
        return _response(
            backend_configured=True,
            connected=False,
            buckets=names,
            error=f"missing buckets: {', '.join(missing)}",
        )

    return _response(
        backend_configured=True,
        connected=True,
        buckets=names,
        error=None,
    )

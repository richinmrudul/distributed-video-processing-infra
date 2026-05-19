from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Header, HTTPException, status

from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics import ADMIN_AUTH_REQUESTS_TOTAL
from app.core.tracing import start_span

log = get_logger(__name__)


def _record_admin_auth_outcome(outcome: str) -> None:
    ADMIN_AUTH_REQUESTS_TOTAL.labels(outcome=outcome).inc()
    log.warning("admin_auth_check_failed", reason=outcome)


def require_admin_api_key(
    x_admin_api_key: Annotated[str | None, Header(alias="X-Admin-API-Key")] = None,
) -> None:
    with start_span(
        "app.admin_auth",
        "admin_auth_check",
        attributes={"admin_auth.enabled": settings.admin_auth_enabled},
    ) as span:
        if not settings.admin_auth_enabled:
            outcome = "disabled"
            ADMIN_AUTH_REQUESTS_TOTAL.labels(outcome=outcome).inc()
            span.set_attribute("admin_auth.outcome", outcome)
            log.info("admin_auth_disabled", reason=outcome)
            return

        expected_key = (settings.admin_api_key or "").strip()
        if not expected_key:
            outcome = "misconfigured"
            _record_admin_auth_outcome(outcome)
            span.set_attribute("admin_auth.outcome", outcome)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Admin authentication is not configured",
            )

        if x_admin_api_key is None:
            outcome = "missing_key"
            _record_admin_auth_outcome(outcome)
            span.set_attribute("admin_auth.outcome", outcome)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Admin API key required",
            )

        if not secrets.compare_digest(x_admin_api_key, expected_key):
            outcome = "invalid_key"
            _record_admin_auth_outcome(outcome)
            span.set_attribute("admin_auth.outcome", outcome)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid admin API key",
            )

        outcome = "allowed"
        ADMIN_AUTH_REQUESTS_TOTAL.labels(outcome=outcome).inc()
        span.set_attribute("admin_auth.outcome", outcome)

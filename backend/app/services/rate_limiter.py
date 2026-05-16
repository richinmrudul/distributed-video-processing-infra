import time
from dataclasses import dataclass

from fastapi import Request
from redis import Redis

from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics import (
    UPLOAD_RATE_LIMIT_REMAINING,
    VIDEO_UPLOAD_RATE_LIMIT_CHECKS_TOTAL,
    VIDEO_UPLOAD_RATE_LIMIT_REJECTIONS_TOTAL,
)
from app.core.tracing import start_span

log = get_logger(__name__)


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    reason: str | None
    limit: int
    remaining: int
    reset_seconds: int
    client_identifier: str


def get_client_identifier(request: Request) -> str:
    # Local/dev behavior: trust X-Forwarded-For for easier proxy testing. In production,
    # only trust this header when set by a controlled edge proxy.
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        first_ip = forwarded_for.split(",", 1)[0].strip()
        if first_ip:
            return first_ip
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def client_type(client_identifier: str) -> str:
    return "unknown" if client_identifier == "unknown" else "ip"


class UploadRateLimiter:
    def check_upload_allowed(self, request: Request) -> RateLimitDecision:
        identifier = get_client_identifier(request)
        with start_span("app.rate_limiter", "upload_rate_limit_check") as span:
            decision = self._check_upload_allowed(identifier)
            ctype = client_type(identifier)
            span.set_attribute("rate_limit.allowed", decision.allowed)
            span.set_attribute("rate_limit.reason", decision.reason or "")
            span.set_attribute("rate_limit.limit", decision.limit)
            span.set_attribute("rate_limit.remaining", decision.remaining)
            span.set_attribute("rate_limit.reset_seconds", decision.reset_seconds)
            span.set_attribute("client.type", ctype)
            return decision

    def _check_upload_allowed(self, client_identifier: str) -> RateLimitDecision:
        limit = settings.upload_rate_limit_max_requests
        window_seconds = settings.upload_rate_limit_window_seconds
        ctype = client_type(client_identifier)

        if not settings.upload_rate_limit_enabled:
            VIDEO_UPLOAD_RATE_LIMIT_CHECKS_TOTAL.labels(outcome="disabled").inc()
            UPLOAD_RATE_LIMIT_REMAINING.labels(client_type=ctype).set(limit)
            return RateLimitDecision(
                allowed=True,
                reason="rate_limit_disabled",
                limit=limit,
                remaining=limit,
                reset_seconds=window_seconds,
                client_identifier=client_identifier,
            )

        now = int(time.time())
        window_start = (now // window_seconds) * window_seconds
        reset_seconds = max(1, window_start + window_seconds - now)
        key = f"upload_rate:{client_identifier}:{window_start}"
        conn = Redis.from_url(settings.redis_url, decode_responses=False)
        try:
            count = int(conn.incr(key))
            if count == 1:
                conn.expire(key, window_seconds)
            remaining = max(0, limit - count)
            UPLOAD_RATE_LIMIT_REMAINING.labels(client_type=ctype).set(remaining)

            if count > limit:
                return self._reject(
                    reason="rate_limited",
                    outcome="rate_limited",
                    limit=limit,
                    remaining=0,
                    reset_seconds=reset_seconds,
                    client_identifier=client_identifier,
                )

            VIDEO_UPLOAD_RATE_LIMIT_CHECKS_TOTAL.labels(outcome="allowed").inc()
            return RateLimitDecision(
                allowed=True,
                reason=None,
                limit=limit,
                remaining=remaining,
                reset_seconds=reset_seconds,
                client_identifier=client_identifier,
            )
        except Exception as exc:
            log.warning("upload_rate_limit_check_failed", error=str(exc))
            return self._reject(
                reason="rate_limiter_unavailable",
                outcome="unavailable",
                limit=limit,
                remaining=0,
                reset_seconds=window_seconds,
                client_identifier=client_identifier,
            )
        finally:
            conn.close()

    def _reject(
        self,
        *,
        reason: str,
        outcome: str,
        limit: int,
        remaining: int,
        reset_seconds: int,
        client_identifier: str,
    ) -> RateLimitDecision:
        ctype = client_type(client_identifier)
        VIDEO_UPLOAD_RATE_LIMIT_CHECKS_TOTAL.labels(outcome=outcome).inc()
        VIDEO_UPLOAD_RATE_LIMIT_REJECTIONS_TOTAL.labels(reason=reason).inc()
        UPLOAD_RATE_LIMIT_REMAINING.labels(client_type=ctype).set(remaining)
        return RateLimitDecision(
            allowed=False,
            reason=reason,
            limit=limit,
            remaining=remaining,
            reset_seconds=reset_seconds,
            client_identifier=client_identifier,
        )

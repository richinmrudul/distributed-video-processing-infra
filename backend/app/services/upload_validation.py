from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import Request, UploadFile

from app.core.config import settings
from app.core.metrics import (
    UPLOAD_VALIDATION_CONTENT_LENGTH_BYTES,
    VIDEO_UPLOAD_VALIDATION_CHECKS_TOTAL,
    VIDEO_UPLOAD_VALIDATION_REJECTIONS_TOTAL,
)
from app.core.tracing import start_span


@dataclass(frozen=True)
class UploadValidationDecision:
    allowed: bool
    reason: str | None
    max_bytes: int
    content_length: int | None
    filename: str | None
    content_type: str | None


class UploadValidator:
    def validate_request_metadata(
        self,
        request: Request,
        file: UploadFile | None = None,
    ) -> UploadValidationDecision:
        content_length = _parse_content_length(request.headers.get("content-length"))
        filename = getattr(file, "filename", None) if file is not None else None
        content_type = getattr(file, "content_type", None) if file is not None else None
        extension = _extension(filename)

        with start_span("app.upload_validation", "upload_validation_check") as span:
            if content_length is not None:
                UPLOAD_VALIDATION_CONTENT_LENGTH_BYTES.set(content_length)

            if not settings.upload_validation_enabled:
                decision = self._allowed("upload_validation_disabled", content_length, filename, content_type)
                VIDEO_UPLOAD_VALIDATION_CHECKS_TOTAL.labels(outcome="disabled").inc()
            elif content_length is not None and content_length > settings.max_upload_bytes:
                decision = self._rejected("upload_too_large", content_length, filename, content_type)
            else:
                decision = self._allowed(None, content_length, filename, content_type)

            _set_span_attrs(span, decision, extension)
            return decision

    def validate_upload_file(self, file: UploadFile) -> UploadValidationDecision:
        filename = getattr(file, "filename", None)
        content_type = (getattr(file, "content_type", None) or "").lower() or None
        extension = _extension(filename)

        with start_span("app.upload_validation", "upload_validation_check") as span:
            if not settings.upload_validation_enabled:
                decision = self._allowed("upload_validation_disabled", None, filename, content_type)
                VIDEO_UPLOAD_VALIDATION_CHECKS_TOTAL.labels(outcome="disabled").inc()
            elif not filename:
                decision = self._rejected("missing_filename", None, filename, content_type)
            elif extension not in settings.allowed_video_extensions_list:
                decision = self._rejected("unsupported_extension", None, filename, content_type)
            elif content_type and content_type not in settings.allowed_video_content_types_list:
                decision = self._rejected("unsupported_content_type", None, filename, content_type)
            elif _is_empty_file(file):
                decision = self._rejected("empty_upload", 0, filename, content_type)
            else:
                decision = self._allowed(None, None, filename, content_type)
                VIDEO_UPLOAD_VALIDATION_CHECKS_TOTAL.labels(outcome="allowed").inc()

            _set_span_attrs(span, decision, extension)
            return decision

    def _allowed(
        self,
        reason: str | None,
        content_length: int | None,
        filename: str | None,
        content_type: str | None,
    ) -> UploadValidationDecision:
        return UploadValidationDecision(
            allowed=True,
            reason=reason,
            max_bytes=settings.max_upload_bytes,
            content_length=content_length,
            filename=filename,
            content_type=content_type,
        )

    def _rejected(
        self,
        reason: str,
        content_length: int | None,
        filename: str | None,
        content_type: str | None,
    ) -> UploadValidationDecision:
        VIDEO_UPLOAD_VALIDATION_CHECKS_TOTAL.labels(outcome="rejected").inc()
        VIDEO_UPLOAD_VALIDATION_REJECTIONS_TOTAL.labels(reason=reason).inc()
        if content_length is not None:
            UPLOAD_VALIDATION_CONTENT_LENGTH_BYTES.set(content_length)
        return UploadValidationDecision(
            allowed=False,
            reason=reason,
            max_bytes=settings.max_upload_bytes,
            content_length=content_length,
            filename=filename,
            content_type=content_type,
        )


def _parse_content_length(value: str | None) -> int | None:
    if not value:
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


def _extension(filename: str | None) -> str | None:
    if not filename:
        return None
    return Path(filename).suffix.lower()


def _is_empty_file(file: UploadFile) -> bool:
    fp: Any = getattr(file, "file", None)
    if fp is None:
        return False
    try:
        current = fp.tell()
        fp.seek(0, 2)
        size = fp.tell()
        fp.seek(current)
        return size == 0
    except Exception:
        return False


def _set_span_attrs(span: Any, decision: UploadValidationDecision, extension: str | None) -> None:
    span.set_attribute("upload_validation.allowed", decision.allowed)
    span.set_attribute("upload_validation.reason", decision.reason or "")
    span.set_attribute("upload.max_bytes", decision.max_bytes)
    if decision.content_length is not None:
        span.set_attribute("upload.content_length", decision.content_length)
    if decision.content_type:
        span.set_attribute("upload.content_type", decision.content_type)
    if extension:
        span.set_attribute("upload.extension", extension)

"""Short, API-safe error messages for persisted job failures."""

from app.services.processing_service import ProcessingError

MAX_ERROR_MESSAGE_LEN = 500


def sanitize_processing_error_message(exc: ProcessingError) -> str:
    raw = str(exc)
    lower = raw.lower()
    if "moov atom not found" in lower:
        return "Invalid video file: moov atom not found"
    if "invalid data found when processing input" in lower:
        return "Invalid video file: FFmpeg could not parse input"
    return _truncate_safe(raw)


def sanitize_error_message(exc: BaseException) -> str:
    if isinstance(exc, ProcessingError):
        return sanitize_processing_error_message(exc)
    return _truncate_safe(str(exc))


def _truncate_safe(text: str) -> str:
    single = " ".join(text.split())
    if not single:
        return "Processing failed"
    if len(single) <= MAX_ERROR_MESSAGE_LEN:
        return single
    return single[: MAX_ERROR_MESSAGE_LEN - 3] + "..."

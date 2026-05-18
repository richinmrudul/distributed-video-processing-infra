from app.services.processing_service import ProcessingError
from app.utils.error_messages import MAX_ERROR_MESSAGE_LEN, sanitize_error_message


def test_moov_atom_error_gets_safe_message():
    assert sanitize_error_message(ProcessingError("ffmpeg: moov atom not found")) == (
        "Invalid video file: moov atom not found"
    )


def test_invalid_data_error_gets_safe_parse_message():
    assert sanitize_error_message(ProcessingError("Invalid data found when processing input")) == (
        "Invalid video file: FFmpeg could not parse input"
    )


def test_unknown_long_error_is_truncated():
    message = sanitize_error_message(RuntimeError("x" * 1000))
    assert len(message) == MAX_ERROR_MESSAGE_LEN
    assert message.endswith("...")


def test_empty_error_gets_generic_safe_message():
    assert sanitize_error_message(RuntimeError("")) == "Processing failed"

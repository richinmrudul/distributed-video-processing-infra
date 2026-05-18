from app.core.config import settings
from app.services.upload_validation import UploadValidator

from tests.conftest import FakeUploadFile, fake_request


def test_validation_disabled_allows_metadata_and_file(monkeypatch):
    monkeypatch.setattr(settings, "upload_validation_enabled", False)
    validator = UploadValidator()

    assert validator.validate_request_metadata(fake_request({"content-length": "999999999"})).allowed
    assert validator.validate_upload_file(FakeUploadFile(filename=None, content_type="text/plain", body=b"")).allowed


def test_unsupported_extension_rejects(monkeypatch):
    monkeypatch.setattr(settings, "upload_validation_enabled", True)
    decision = UploadValidator().validate_upload_file(FakeUploadFile(filename="clip.exe"))

    assert not decision.allowed
    assert decision.reason == "unsupported_extension"


def test_unsupported_content_type_rejects(monkeypatch):
    monkeypatch.setattr(settings, "upload_validation_enabled", True)
    decision = UploadValidator().validate_upload_file(FakeUploadFile(content_type="text/plain"))

    assert not decision.allowed
    assert decision.reason == "unsupported_content_type"


def test_missing_filename_rejects(monkeypatch):
    monkeypatch.setattr(settings, "upload_validation_enabled", True)
    decision = UploadValidator().validate_upload_file(FakeUploadFile(filename=None))

    assert not decision.allowed
    assert decision.reason == "missing_filename"


def test_empty_upload_rejects(monkeypatch):
    monkeypatch.setattr(settings, "upload_validation_enabled", True)
    decision = UploadValidator().validate_upload_file(FakeUploadFile(body=b""))

    assert not decision.allowed
    assert decision.reason == "empty_upload"


def test_allowed_mp4_passes(monkeypatch):
    monkeypatch.setattr(settings, "upload_validation_enabled", True)
    decision = UploadValidator().validate_upload_file(FakeUploadFile(filename="clip.mp4", content_type="video/mp4"))

    assert decision.allowed
    assert decision.reason is None


def test_content_length_above_max_rejects(monkeypatch):
    monkeypatch.setattr(settings, "upload_validation_enabled", True)
    monkeypatch.setattr(settings, "max_upload_bytes", 10)
    decision = UploadValidator().validate_request_metadata(fake_request({"content-length": "11"}))

    assert not decision.allowed
    assert decision.reason == "upload_too_large"


def test_missing_content_length_does_not_reject(monkeypatch):
    monkeypatch.setattr(settings, "upload_validation_enabled", True)
    decision = UploadValidator().validate_request_metadata(fake_request())

    assert decision.allowed
    assert decision.content_length is None

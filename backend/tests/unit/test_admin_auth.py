import pytest
from fastapi import HTTPException

from app.core import admin_auth
from app.core.admin_auth import require_admin_api_key


def test_admin_auth_disabled_allows_without_key(monkeypatch):
    monkeypatch.setattr(admin_auth.settings, "admin_auth_enabled", False)

    assert require_admin_api_key(None) is None


def test_admin_auth_correct_key_allows(monkeypatch):
    monkeypatch.setattr(admin_auth.settings, "admin_auth_enabled", True)
    monkeypatch.setattr(admin_auth.settings, "admin_api_key", "dev-admin-key")

    assert require_admin_api_key("dev-admin-key") is None


def test_admin_auth_missing_key_returns_401(monkeypatch):
    monkeypatch.setattr(admin_auth.settings, "admin_auth_enabled", True)
    monkeypatch.setattr(admin_auth.settings, "admin_api_key", "dev-admin-key")

    with pytest.raises(HTTPException) as exc:
        require_admin_api_key(None)

    assert exc.value.status_code == 401
    assert exc.value.detail == "Admin API key required"


def test_admin_auth_wrong_key_returns_403(monkeypatch):
    monkeypatch.setattr(admin_auth.settings, "admin_auth_enabled", True)
    monkeypatch.setattr(admin_auth.settings, "admin_api_key", "dev-admin-key")

    with pytest.raises(HTTPException) as exc:
        require_admin_api_key("wrong")

    assert exc.value.status_code == 403
    assert exc.value.detail == "Invalid admin API key"


def test_admin_auth_missing_configured_key_returns_503(monkeypatch):
    monkeypatch.setattr(admin_auth.settings, "admin_auth_enabled", True)
    monkeypatch.setattr(admin_auth.settings, "admin_api_key", "")

    with pytest.raises(HTTPException) as exc:
        require_admin_api_key("dev-admin-key")

    assert exc.value.status_code == 503
    assert exc.value.detail == "Admin authentication is not configured"


def test_admin_auth_uses_constant_time_compare(monkeypatch):
    calls = []

    def fake_compare_digest(provided, expected):
        calls.append((provided, expected))
        return True

    monkeypatch.setattr(admin_auth.settings, "admin_auth_enabled", True)
    monkeypatch.setattr(admin_auth.settings, "admin_api_key", "dev-admin-key")
    monkeypatch.setattr(admin_auth.secrets, "compare_digest", fake_compare_digest)

    require_admin_api_key("provided-key")

    assert calls == [("provided-key", "dev-admin-key")]

from __future__ import annotations

import pytest

from app.core.config import Settings, parse_cors_allowed_origins


def production_settings(**overrides):
    values = {
        "app_env": "production",
        "admin_auth_enabled": True,
        "admin_api_key": "strong-production-admin-key",
        "cors_allowed_origins": "https://console.example.com",
        "database_url": "postgresql+psycopg2://video:secret@prod-postgres.example.com:5432/video",
        "redis_url": "redis://prod-redis.example.com:6379/0",
        "storage_backend": "object",
        "object_storage_access_key": "prod-access-key",
        "object_storage_secret_key": "prod-secret-key",
    }
    values.update(overrides)
    return Settings(**values)


def test_cors_origin_parser_trims_whitespace_and_ignores_empty_entries():
    origins = parse_cors_allowed_origins(" http://localhost:3001, ,http://127.0.0.1:3002 ")

    assert origins == ["http://localhost:3001", "http://127.0.0.1:3002"]


def test_development_config_allows_local_defaults():
    settings = Settings(app_env="development")

    assert settings.admin_api_key == "dev-admin-key"
    assert "http://localhost:3001" in settings.cors_allowed_origins_list


def test_production_config_rejects_dev_admin_key():
    with pytest.raises(Exception, match="ADMIN_API_KEY must not use"):
        production_settings(admin_api_key="dev-admin-key")


def test_production_config_rejects_wildcard_cors():
    with pytest.raises(Exception, match="CORS_ALLOWED_ORIGINS"):
        production_settings(cors_allowed_origins="https://console.example.com,*")


def test_production_config_rejects_disabled_admin_auth():
    with pytest.raises(Exception, match="ADMIN_AUTH_ENABLED"):
        production_settings(admin_auth_enabled=False)


def test_production_config_rejects_local_database_and_redis_defaults():
    with pytest.raises(Exception, match="DATABASE_URL"):
        production_settings(database_url="postgresql+psycopg2://video:video@localhost:5432/video")

    with pytest.raises(Exception, match="REDIS_URL"):
        production_settings(redis_url="redis://redis:6379/0")


def test_production_config_rejects_placeholder_object_storage_secrets():
    with pytest.raises(Exception, match="OBJECT_STORAGE_ACCESS_KEY"):
        production_settings(object_storage_access_key="replace-me")

    with pytest.raises(Exception, match="OBJECT_STORAGE_SECRET_KEY"):
        production_settings(object_storage_secret_key="minioadmin")

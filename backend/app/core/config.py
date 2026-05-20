from pathlib import Path

from pydantic import ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_CORS_ALLOWED_ORIGINS = (
    "http://localhost:3001,http://127.0.0.1:3001,http://localhost:3002,http://127.0.0.1:3002"
)


def parse_cors_allowed_origins(value: str) -> list[str]:
    return [origin.strip() for origin in value.split(",") if origin.strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Distributed Video Processing API"
    app_env: str = "development"
    debug: bool = False
    cors_allowed_origins: str = DEFAULT_CORS_ALLOWED_ORIGINS

    database_url: str = "postgresql+psycopg2://video:video@localhost:5432/video"

    redis_url: str = "redis://redis:6379/0"
    queue_name: str = "video-processing"

    rq_job_timeout_seconds: int = 600
    worker_metrics_port: int = 9100

    upload_admission_control_enabled: bool = True
    max_queue_depth_for_uploads: int = 50
    min_available_workers_for_uploads: int = 1

    upload_rate_limit_enabled: bool = True
    upload_rate_limit_max_requests: int = 10
    upload_rate_limit_window_seconds: int = 60

    upload_validation_enabled: bool = True
    max_upload_bytes: int = 104857600
    allowed_video_extensions: str = ".mp4,.mov,.mkv,.webm"
    allowed_video_content_types: str = (
        "video/mp4,video/quicktime,video/x-matroska,video/webm,application/octet-stream"
    )
    upload_idempotency_enabled: bool = True
    idempotency_key_max_length: int = 128

    admin_auth_enabled: bool = True
    admin_api_key: str = "dev-admin-key"

    cleanup_enabled: bool = True
    cleanup_completed_after_days: int = 7
    cleanup_failed_after_days: int = 14
    cleanup_delete_db_rows: bool = False
    cleanup_batch_size: int = 100

    stuck_processing_timeout_seconds: int = 300
    stuck_queued_timeout_seconds: int = 300
    stuck_job_recovery_enabled: bool = True

    reconciler_enabled: bool = True
    reconciler_interval_seconds: int = 60
    reconciler_startup_delay_seconds: int = 10
    reconciler_oneshot: bool = False
    reconciler_metrics_port: int = 9200
    reconciler_lock_enabled: bool = True
    reconciler_lock_key: str = "reconciler:stuck-job-recovery"
    reconciler_lock_ttl_seconds: int = 55
    reconciler_lock_acquire_timeout_seconds: int = 2

    storage_root: Path = Path("storage")

    # S3-compatible object storage (MinIO). Used when STORAGE_BACKEND=object.
    object_storage_endpoint: str = "http://minio:9000"
    object_storage_public_endpoint: str = "http://localhost:9000"
    object_storage_access_key: str = "minioadmin"
    object_storage_secret_key: str = "minioadmin"
    object_storage_region: str = "us-east-1"
    object_storage_secure: bool = False

    raw_video_bucket: str = "raw-videos"
    processed_video_bucket: str = "processed-videos"
    thumbnail_bucket: str = "thumbnails"

    # local | object (Compose may set object; bare-metal default local).
    storage_backend: str = "local"

    presigned_url_expires_seconds: int = 3600

    log_level: str = "INFO"
    log_json: bool = False

    tracing_enabled: bool = True
    otel_service_name: str = "video-processing-api"
    otel_exporter_otlp_endpoint: str = "http://jaeger:4317"

    @model_validator(mode="after")
    def validate_production_config(self) -> "Settings":
        if self.app_env.strip().lower() != "production":
            return self

        errors: list[str] = []
        if not self.admin_auth_enabled:
            errors.append("ADMIN_AUTH_ENABLED must be true when APP_ENV=production")
        if not self.admin_api_key.strip():
            errors.append("ADMIN_API_KEY must be set when APP_ENV=production")
        if self.admin_api_key.strip() == "dev-admin-key":
            errors.append("ADMIN_API_KEY must not use the Docker Compose dev key when APP_ENV=production")
        if "*" in parse_cors_allowed_origins(self.cors_allowed_origins):
            errors.append("CORS_ALLOWED_ORIGINS must not contain '*' when APP_ENV=production")
        if (
            self.database_url == "postgresql+psycopg2://video:video@localhost:5432/video"
            or "@localhost:" in self.database_url
            or "@127.0.0.1:" in self.database_url
            or "@db:5432" in self.database_url
        ):
            errors.append("DATABASE_URL must not point to the local development database when APP_ENV=production")
        if self.redis_url in ("redis://redis:6379/0", "redis://localhost:6379/0", "redis://127.0.0.1:6379/0"):
            errors.append("REDIS_URL must not use the local development Redis URL when APP_ENV=production")
        unsafe_storage_values = {"", "minioadmin", "replace-me", "changeme", "change-me"}
        if self.storage_backend == "object":
            if self.object_storage_access_key.strip() in unsafe_storage_values:
                errors.append("OBJECT_STORAGE_ACCESS_KEY must be a real production value when APP_ENV=production")
            if self.object_storage_secret_key.strip() in unsafe_storage_values:
                errors.append("OBJECT_STORAGE_SECRET_KEY must be a real production value when APP_ENV=production")

        if errors:
            raise ValueError("Unsafe production configuration: " + "; ".join(errors))
        return self

    @field_validator(
        "tracing_enabled",
        "upload_admission_control_enabled",
        "upload_rate_limit_enabled",
        "upload_validation_enabled",
        "upload_idempotency_enabled",
        "admin_auth_enabled",
        "cleanup_enabled",
        "cleanup_delete_db_rows",
        "stuck_job_recovery_enabled",
        "reconciler_enabled",
        "reconciler_oneshot",
        "reconciler_lock_enabled",
        mode="before",
    )
    @classmethod
    def coerce_bool(cls, v: object) -> bool:
        if isinstance(v, bool):
            return v
        if v is None:
            return True
        s = str(v).strip().lower()
        if s in ("0", "false", "no", "n", "off"):
            return False
        if s in ("1", "true", "yes", "y", "on"):
            return True
        return True

    @field_validator("idempotency_key_max_length", mode="before")
    @classmethod
    def coerce_idempotency_key_max_length(cls, v: object) -> int:
        try:
            value = int(str(v).strip())
        except (TypeError, ValueError):
            return 128
        return value if value > 0 else 128

    @field_validator(
        "reconciler_lock_ttl_seconds",
        "reconciler_lock_acquire_timeout_seconds",
        mode="before",
    )
    @classmethod
    def coerce_reconciler_lock_ints(cls, v: object, info: ValidationInfo) -> int:
        defaults = {
            "reconciler_lock_ttl_seconds": 55,
            "reconciler_lock_acquire_timeout_seconds": 2,
        }
        minimums = {
            "reconciler_lock_ttl_seconds": 1,
            "reconciler_lock_acquire_timeout_seconds": 0,
        }
        default = defaults[info.field_name]
        try:
            value = int(str(v).strip())
        except (TypeError, ValueError):
            return default
        return value if value >= minimums[info.field_name] else default

    @field_validator("storage_backend", mode="before")
    @classmethod
    def coerce_storage_backend(cls, v: object) -> str:
        s = str(v or "local").strip().lower()
        if s not in ("local", "object"):
            return "local"
        return s

    @field_validator("object_storage_secure", mode="before")
    @classmethod
    def coerce_object_storage_secure(cls, v: object) -> bool:
        if isinstance(v, bool):
            return v
        if v is None:
            return False
        if isinstance(v, (int, float)):
            return bool(v)
        s = str(v).strip().lower()
        if s in ("0", "false", "no", "n", "off", ""):
            return False
        if s in ("1", "true", "yes", "y", "on"):
            return True
        return False

    @property
    def raw_dir(self) -> Path:
        return self.storage_root / "raw"

    @property
    def allowed_video_extensions_list(self) -> list[str]:
        return [item.strip().lower() for item in self.allowed_video_extensions.split(",") if item.strip()]

    @property
    def allowed_video_content_types_list(self) -> list[str]:
        return [item.strip().lower() for item in self.allowed_video_content_types.split(",") if item.strip()]

    @property
    def cors_allowed_origins_list(self) -> list[str]:
        return parse_cors_allowed_origins(self.cors_allowed_origins)

    @property
    def processed_dir(self) -> Path:
        return self.storage_root / "processed"

    @property
    def thumbnails_dir(self) -> Path:
        return self.storage_root / "thumbnails"


settings = Settings()

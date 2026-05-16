from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Distributed Video Processing API"
    debug: bool = False

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

    @field_validator("tracing_enabled", "upload_admission_control_enabled", "upload_rate_limit_enabled", mode="before")
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
    def processed_dir(self) -> Path:
        return self.storage_root / "processed"

    @property
    def thumbnails_dir(self) -> Path:
        return self.storage_root / "thumbnails"


settings = Settings()

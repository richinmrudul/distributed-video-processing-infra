from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Distributed Video Processing API"
    debug: bool = False

    database_url: str = "postgresql+psycopg2://video:video@localhost:5432/video"

    redis_url: str = "redis://redis:6379/0"
    queue_name: str = "video-processing"

    storage_root: Path = Path("storage")

    log_level: str = "INFO"
    log_json: bool = False

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

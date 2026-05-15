from pydantic import BaseModel, Field


class StorageHealthResponse(BaseModel):
    backend_configured: bool = Field(
        description="True when required object storage settings are non-empty.",
    )
    storage_backend: str = Field(description="Active storage mode (e.g. local).")
    endpoint: str
    public_endpoint: str = Field(
        description="Client-facing S3 endpoint used in presigned URLs (may differ from internal endpoint).",
    )
    secure: bool
    expected_buckets: list[str] = Field(description="Buckets the app is configured to use.")
    buckets: list[str] = Field(default_factory=list, description="Buckets visible from list_buckets when connected.")
    connected: bool = False
    error: str | None = None

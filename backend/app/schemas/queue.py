from pydantic import BaseModel, Field


class QueueHealthResponse(BaseModel):
    redis_connected: bool = Field(description="Whether a Redis PING succeeded.")
    queue_name: str
    queued_jobs_count: int = 0
    failed_jobs_count: int = 0
    started_jobs_count: int = 0
    deferred_jobs_count: int = 0
    redis_error: str | None = Field(None, description="Present when redis_connected is false.")

import enum

from pydantic import BaseModel, ConfigDict, Field


class QueuePressureLevel(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class QueueHealthResponse(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    redis_connected: bool = Field(description="Whether a Redis PING succeeded.")
    queue_name: str
    queued_jobs_count: int = 0
    failed_jobs_count: int = 0
    started_jobs_count: int = 0
    deferred_jobs_count: int = 0
    finished_jobs_count: int = 0
    active_jobs_count: int = Field(
        0,
        description="Jobs currently marked started in RQ (same source as started_jobs_count).",
    )
    worker_count: int = 0
    worker_names: list[str] = Field(default_factory=list)
    queue_latency_estimate_seconds: float | None = Field(
        None,
        description="Seconds since enqueue for the head job, if available.",
    )
    queue_pressure_level: QueuePressureLevel | None = Field(
        None,
        description="Heuristic from queued depth only (LOW ≤5, MEDIUM 6–20, HIGH ≥21).",
    )
    redis_error: str | None = Field(None, description="Present when redis_connected is false or metrics failed.")

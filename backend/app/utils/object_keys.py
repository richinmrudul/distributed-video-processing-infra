"""Deterministic S3 object keys for video artifacts."""

from pathlib import Path


def safe_filename(original_filename: str) -> str:
    base = Path(original_filename).name.strip()
    if not base:
        return "video.bin"
    return base.replace("/", "_").replace("\\", "_")


def raw_object_key(video_id: str, original_filename: str) -> str:
    return f"videos/{video_id}/raw/{safe_filename(original_filename)}"


def processed_object_key(video_id: str) -> str:
    return f"videos/{video_id}/processed/{video_id}.mp4"


def thumbnail_object_key(video_id: str) -> str:
    return f"videos/{video_id}/thumbnails/{video_id}.jpg"


def s3_uri(bucket: str, object_key: str) -> str:
    return f"s3://{bucket}/{object_key}"

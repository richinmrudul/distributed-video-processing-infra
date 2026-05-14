import shutil
import subprocess
from pathlib import Path

from app.core.config import settings


class ProcessingError(Exception):
    pass


class ProcessingService:
    """FFmpeg-based transcoding and thumbnails. Designed to be invoked from workers later."""

    def __init__(
        self,
        processed_dir: Path | None = None,
        thumbnails_dir: Path | None = None,
    ) -> None:
        self._processed_dir = processed_dir or settings.processed_dir
        self._thumbnails_dir = thumbnails_dir or settings.thumbnails_dir

    def ensure_directories(self) -> None:
        self._processed_dir.mkdir(parents=True, exist_ok=True)
        self._thumbnails_dir.mkdir(parents=True, exist_ok=True)

    def ffmpeg_available(self) -> bool:
        return shutil.which("ffmpeg") is not None

    def process(self, video_id: str, raw_path: Path) -> tuple[Path, Path]:
        if not self.ffmpeg_available():
            raise ProcessingError("ffmpeg executable not found on PATH")

        self.ensure_directories()
        processed_path = self._processed_dir / f"{video_id}.mp4"
        thumbnail_path = self._thumbnails_dir / f"{video_id}.jpg"

        transcode = [
            "ffmpeg",
            "-y",
            "-i",
            str(raw_path),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            str(processed_path),
        ]
        thumb = [
            "ffmpeg",
            "-y",
            "-ss",
            "0",
            "-i",
            str(raw_path),
            "-vframes",
            "1",
            "-q:v",
            "2",
            str(thumbnail_path),
        ]

        for cmd in (transcode, thumb):
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if result.returncode != 0:
                stderr = (result.stderr or "").strip()
                raise ProcessingError(f"ffmpeg failed ({result.returncode}): {stderr[-2000:]}")

        return processed_path, thumbnail_path

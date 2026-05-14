import shutil
import subprocess
from pathlib import Path
from typing import NamedTuple

from app.core.config import settings


class ProcessingError(Exception):
    pass


class ProcessingResult(NamedTuple):
    processed_path: Path
    thumbnail_path: Path


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

    def process_paths(
        self,
        input_path: Path,
        output_video_path: Path,
        output_thumbnail_path: Path,
    ) -> ProcessingResult:
        """Run FFmpeg with explicit paths (object mode temp files or custom locations)."""
        if not self.ffmpeg_available():
            raise ProcessingError("ffmpeg executable not found on PATH")

        output_video_path.parent.mkdir(parents=True, exist_ok=True)
        output_thumbnail_path.parent.mkdir(parents=True, exist_ok=True)

        transcode = [
            "ffmpeg",
            "-y",
            "-i",
            str(input_path),
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
            str(output_video_path),
        ]
        thumb = [
            "ffmpeg",
            "-y",
            "-ss",
            "0",
            "-i",
            str(input_path),
            "-vframes",
            "1",
            "-q:v",
            "2",
            str(output_thumbnail_path),
        ]

        for cmd in (transcode, thumb):
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if result.returncode != 0:
                stderr = (result.stderr or "").strip()
                raise ProcessingError(f"ffmpeg failed ({result.returncode}): {stderr[-2000:]}")

        return ProcessingResult(output_video_path, output_thumbnail_path)

    def process(self, video_id: str, raw_path: Path) -> tuple[Path, Path]:
        """Local pipeline: write under configured processed/thumbnails directories."""
        self.ensure_directories()
        processed_path = self._processed_dir / f"{video_id}.mp4"
        thumbnail_path = self._thumbnails_dir / f"{video_id}.jpg"
        r = self.process_paths(raw_path, processed_path, thumbnail_path)
        return r.processed_path, r.thumbnail_path

from pathlib import Path

from fastapi import UploadFile

from app.core.config import settings


class StorageService:
    def __init__(self, raw_dir: Path | None = None) -> None:
        self._raw_dir = raw_dir or settings.raw_dir

    def ensure_directories(self) -> None:
        self._raw_dir.mkdir(parents=True, exist_ok=True)

    def raw_path_for(self, video_id: str, original_filename: str) -> Path:
        suffix = Path(original_filename).suffix
        if not suffix:
            suffix = ".bin"
        return self._raw_dir / f"{video_id}{suffix}"

    async def save_raw_upload(self, video_id: str, upload: UploadFile) -> Path:
        self.ensure_directories()
        dest = self.raw_path_for(video_id, upload.filename or "video")
        chunk_size = 1024 * 1024
        with dest.open("wb") as out:
            while True:
                chunk = await upload.read(chunk_size)
                if not chunk:
                    break
                out.write(chunk)
        await upload.close()
        return dest

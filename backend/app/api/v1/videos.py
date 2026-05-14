from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.video import VideoStatusResponse, VideoUploadResponse
from app.services.video_service import VideoService

router = APIRouter()


def get_video_service() -> VideoService:
    return VideoService()


@router.post(
    "/upload",
    response_model=VideoUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_video(
    file: UploadFile = File(..., description="Video file to store and process."),
    db: Session = Depends(get_db),
    service: VideoService = Depends(get_video_service),
) -> VideoUploadResponse:
    if not file.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="filename is required")
    job = await service.upload_and_process(db, file)
    return VideoUploadResponse.model_validate(job)


@router.get("/{video_id}/status", response_model=VideoStatusResponse)
def get_video_status(
    video_id: str,
    db: Session = Depends(get_db),
    service: VideoService = Depends(get_video_service),
) -> VideoStatusResponse:
    job = service.get_job(db, video_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video job not found")
    return VideoStatusResponse.model_validate(job)

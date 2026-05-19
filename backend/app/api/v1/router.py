from fastapi import APIRouter

from app.api.v1 import jobs, queue, storage, videos

api_router = APIRouter()
api_router.include_router(jobs.router, prefix="/jobs", tags=["Admin Jobs"])
api_router.include_router(videos.router, prefix="/videos", tags=["Videos"])
api_router.include_router(queue.router, prefix="/queue", tags=["Queue"])
api_router.include_router(storage.router, prefix="/storage", tags=["Storage"])

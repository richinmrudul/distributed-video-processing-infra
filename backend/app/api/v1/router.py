from fastapi import APIRouter

from app.api.v1 import queue, videos

api_router = APIRouter()
api_router.include_router(videos.router, prefix="/videos", tags=["videos"])
api_router.include_router(queue.router, prefix="/queue", tags=["queue"])

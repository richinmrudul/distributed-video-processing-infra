from fastapi import APIRouter

from app.api.v1 import videos

api_router = APIRouter()
api_router.include_router(videos.router, prefix="/videos", tags=["videos"])

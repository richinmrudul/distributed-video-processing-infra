import uuid


def new_video_id() -> str:
    return str(uuid.uuid4())

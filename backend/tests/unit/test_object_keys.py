from app.utils.object_keys import (
    processed_object_key,
    raw_object_key,
    s3_uri,
    safe_filename,
    thumbnail_object_key,
)


def test_raw_object_key_uses_video_raw_prefix_and_safe_filename():
    assert raw_object_key("vid-1", "clip.mp4") == "videos/vid-1/raw/clip.mp4"


def test_processed_and_thumbnail_object_keys_are_deterministic():
    assert processed_object_key("vid-1") == "videos/vid-1/processed/vid-1.mp4"
    assert thumbnail_object_key("vid-1") == "videos/vid-1/thumbnails/vid-1.jpg"


def test_s3_uri_formats_bucket_and_key():
    assert s3_uri("raw-videos", "videos/vid-1/raw/clip.mp4") == "s3://raw-videos/videos/vid-1/raw/clip.mp4"


def test_safe_filename_keeps_spaces_and_strips_path_traversal():
    assert safe_filename("my clip.mp4") == "my clip.mp4"
    assert safe_filename("../../evil.mp4") == "evil.mp4"


def test_safe_filename_handles_weird_and_empty_names():
    assert safe_filename("weird @#$%.mp4") == "weird @#$%.mp4"
    assert safe_filename("   ") == "video.bin"

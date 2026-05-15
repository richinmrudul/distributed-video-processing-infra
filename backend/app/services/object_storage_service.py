"""S3-compatible object storage (MinIO / AWS). Not wired into the video pipeline while STORAGE_BACKEND=local."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import boto3
from botocore.client import BaseClient
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics import record_object_storage_operation

log = get_logger(__name__)


class ObjectStorageError(Exception):
    """Raised when an object storage operation fails."""


def _normalize_endpoint(url: str) -> str:
    return url.strip().rstrip("/")


def _rewrite_presigned_url_for_public(url: str) -> str:
    """Swap internal MinIO host for the browser-facing endpoint; preserve path and query."""
    internal = _normalize_endpoint(settings.object_storage_endpoint)
    public = _normalize_endpoint(settings.object_storage_public_endpoint)
    if not public or public == internal:
        return url
    if url.startswith(internal):
        return public + url[len(internal) :]
    try:
        internal_parts = urlsplit(internal)
        public_parts = urlsplit(public)
        parts = urlsplit(url)
        if parts.netloc == internal_parts.netloc:
            return urlunsplit(
                (
                    public_parts.scheme or parts.scheme,
                    public_parts.netloc,
                    parts.path,
                    parts.query,
                    parts.fragment,
                )
            )
    except Exception as exc:
        log.warning("presigned_url_public_rewrite_failed", error=str(exc), url=url)
        return url
    log.warning(
        "presigned_url_public_rewrite_no_match",
        internal_endpoint=internal,
        url=url,
    )
    return url


class ObjectStorageService:
    def __init__(self) -> None:
        self._client: BaseClient = boto3.client(
            "s3",
            endpoint_url=settings.object_storage_endpoint,
            aws_access_key_id=settings.object_storage_access_key,
            aws_secret_access_key=settings.object_storage_secret_key,
            region_name=settings.object_storage_region,
            use_ssl=settings.object_storage_secure,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )
        self._presign_client: BaseClient | None = None

    def _client_for_presign(self) -> BaseClient:
        """Presign against the public endpoint when it differs (valid SigV4 Host for browsers)."""
        internal = _normalize_endpoint(settings.object_storage_endpoint)
        public = _normalize_endpoint(settings.object_storage_public_endpoint)
        if not public or public == internal:
            return self._client
        if self._presign_client is None:
            public_secure = public.lower().startswith("https://")
            self._presign_client = boto3.client(
                "s3",
                endpoint_url=public,
                aws_access_key_id=settings.object_storage_access_key,
                aws_secret_access_key=settings.object_storage_secret_key,
                region_name=settings.object_storage_region,
                use_ssl=public_secure or settings.object_storage_secure,
                config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
            )
        return self._presign_client

    def check_connection(self) -> bool:
        try:
            self._client.list_buckets()
            return True
        except Exception as exc:
            log.warning("object_storage_connection_failed", error=str(exc))
            return False

    def list_buckets(self) -> list[str]:
        try:
            resp = self._client.list_buckets()
            out: list[str] = []
            for b in resp.get("Buckets", []) or []:
                name = b.get("Name")
                if name:
                    out.append(str(name))
            record_object_storage_operation("list_buckets", "unknown", success=True)
            return out
        except (BotoCoreError, ClientError) as exc:
            record_object_storage_operation("list_buckets", "unknown", success=False)
            log.warning("object_storage_list_buckets_failed", error=str(exc))
            raise ObjectStorageError(f"list_buckets failed: {exc}") from exc
        except Exception as exc:
            record_object_storage_operation("list_buckets", "unknown", success=False)
            log.warning("object_storage_list_buckets_unexpected", error=str(exc))
            raise ObjectStorageError(f"list_buckets failed: {exc}") from exc

    def ensure_bucket_exists(self, bucket_name: str) -> None:
        try:
            self._client.head_bucket(Bucket=bucket_name)
            log.debug("object_storage_bucket_exists", bucket=bucket_name)
            return
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code not in ("404", "NoSuchBucket"):
                raise ObjectStorageError(f"head_bucket failed: {exc}") from exc
        try:
            region = settings.object_storage_region
            if region == "us-east-1":
                self._client.create_bucket(Bucket=bucket_name)
            else:
                self._client.create_bucket(
                    Bucket=bucket_name,
                    CreateBucketConfiguration={"LocationConstraint": region},
                )
            log.info("object_storage_bucket_created", bucket=bucket_name)
        except (BotoCoreError, ClientError) as exc:
            raise ObjectStorageError(f"create_bucket failed: {exc}") from exc

    def upload_file(self, bucket_name: str, object_key: str, file_path: str) -> None:
        path = Path(file_path)
        if not path.is_file():
            raise ObjectStorageError(f"upload source not found: {file_path}")
        try:
            self._client.upload_file(str(path), bucket_name, object_key)
            record_object_storage_operation("upload_file", bucket_name, success=True)
            log.info("object_storage_uploaded", bucket=bucket_name, key=object_key)
        except (BotoCoreError, ClientError) as exc:
            record_object_storage_operation("upload_file", bucket_name, success=False)
            raise ObjectStorageError(f"upload_file failed: {exc}") from exc

    def download_file(self, bucket_name: str, object_key: str, destination_path: str) -> None:
        dest = Path(destination_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._client.download_file(bucket_name, object_key, str(dest))
            record_object_storage_operation("download_file", bucket_name, success=True)
            log.info("object_storage_downloaded", bucket=bucket_name, key=object_key)
        except (BotoCoreError, ClientError) as exc:
            record_object_storage_operation("download_file", bucket_name, success=False)
            raise ObjectStorageError(f"download_file failed: {exc}") from exc

    def object_exists(self, bucket_name: str, object_key: str) -> bool:
        try:
            self._client.head_object(Bucket=bucket_name, Key=object_key)
            record_object_storage_operation("object_exists", bucket_name, success=True)
            return True
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in ("404", "NoSuchKey", "NotFound"):
                record_object_storage_operation("object_exists", bucket_name, success=True)
                return False
            record_object_storage_operation("object_exists", bucket_name, success=False)
            raise ObjectStorageError(f"head_object failed: {exc}") from exc

    def head_object_content_length(self, bucket_name: str, object_key: str) -> int:
        try:
            r = self._client.head_object(Bucket=bucket_name, Key=object_key)
            return int(r.get("ContentLength") or 0)
        except (BotoCoreError, ClientError) as exc:
            raise ObjectStorageError(f"head_object failed: {exc}") from exc

    def generate_presigned_url(
        self,
        bucket_name: str,
        object_key: str,
        expires_in_seconds: int = 3600,
    ) -> str:
        internal = _normalize_endpoint(settings.object_storage_endpoint)
        public = _normalize_endpoint(settings.object_storage_public_endpoint)
        try:
            presign_client = self._client_for_presign()
            url = presign_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket_name, "Key": object_key},
                ExpiresIn=expires_in_seconds,
            )
            if presign_client is self._client and public and public != internal:
                url = _rewrite_presigned_url_for_public(url)
            record_object_storage_operation("generate_presigned_url", bucket_name, success=True)
            log.debug(
                "object_storage_presigned_url",
                bucket=bucket_name,
                key=object_key,
                expires_in_seconds=expires_in_seconds,
                public_endpoint=public or internal,
            )
            return url
        except (BotoCoreError, ClientError) as exc:
            record_object_storage_operation("generate_presigned_url", bucket_name, success=False)
            raise ObjectStorageError(f"generate_presigned_url failed: {exc}") from exc

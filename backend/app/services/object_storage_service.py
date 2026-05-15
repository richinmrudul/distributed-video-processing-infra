"""S3-compatible object storage (MinIO / AWS). Not wired into the video pipeline while STORAGE_BACKEND=local."""

from __future__ import annotations

from pathlib import Path

import boto3
from botocore.client import BaseClient
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)


class ObjectStorageError(Exception):
    """Raised when an object storage operation fails."""


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
            return out
        except (BotoCoreError, ClientError) as exc:
            log.warning("object_storage_list_buckets_failed", error=str(exc))
            raise ObjectStorageError(f"list_buckets failed: {exc}") from exc
        except Exception as exc:
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
            log.info("object_storage_uploaded", bucket=bucket_name, key=object_key)
        except (BotoCoreError, ClientError) as exc:
            raise ObjectStorageError(f"upload_file failed: {exc}") from exc

    def download_file(self, bucket_name: str, object_key: str, destination_path: str) -> None:
        dest = Path(destination_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._client.download_file(bucket_name, object_key, str(dest))
            log.info("object_storage_downloaded", bucket=bucket_name, key=object_key)
        except (BotoCoreError, ClientError) as exc:
            raise ObjectStorageError(f"download_file failed: {exc}") from exc

    def object_exists(self, bucket_name: str, object_key: str) -> bool:
        try:
            self._client.head_object(Bucket=bucket_name, Key=object_key)
            return True
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in ("404", "NoSuchKey", "NotFound"):
                return False
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
        try:
            url = self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket_name, "Key": object_key},
                ExpiresIn=expires_in_seconds,
            )
            log.debug(
                "object_storage_presigned_url",
                bucket=bucket_name,
                key=object_key,
                expires_in_seconds=expires_in_seconds,
            )
            return url
        except (BotoCoreError, ClientError) as exc:
            raise ObjectStorageError(f"generate_presigned_url failed: {exc}") from exc

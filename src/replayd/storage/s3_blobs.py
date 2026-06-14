"""Content-addressed blob store on S3-compatible object storage."""

from __future__ import annotations

import asyncio
from typing import Any

import boto3
from botocore.client import BaseClient
from botocore.exceptions import ClientError

from replayd.storage.blob_store import BlobStore
from replayd.storage.blobs import blob_digest, blob_object_key


class S3BlobStore(BlobStore):
    def __init__(
        self,
        *,
        bucket: str,
        region: str,
        endpoint_url: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
    ) -> None:
        self._bucket = bucket
        self._region = region
        self._endpoint_url = endpoint_url
        self._access_key_id = access_key_id
        self._secret_access_key = secret_access_key
        self._client: BaseClient | None = None

    def _build_client(self) -> BaseClient:
        session_kwargs: dict[str, Any] = {}
        if self._access_key_id and self._secret_access_key:
            session_kwargs["aws_access_key_id"] = self._access_key_id
            session_kwargs["aws_secret_access_key"] = self._secret_access_key
        session = boto3.session.Session(**session_kwargs)
        client_kwargs: dict[str, Any] = {
            "service_name": "s3",
            "region_name": self._region,
        }
        if self._endpoint_url:
            client_kwargs["endpoint_url"] = self._endpoint_url
        return session.client(**client_kwargs)

    @property
    def _s3(self) -> BaseClient:
        if self._client is None:
            raise RuntimeError("S3BlobStore.init() must be called before use")
        return self._client

    async def init(self) -> None:
        self._client = self._build_client()
        await asyncio.to_thread(self._ensure_bucket_exists)

    async def aclose(self) -> None:
        self._client = None

    def _ensure_bucket_exists(self) -> None:
        client = self._s3
        try:
            client.head_bucket(Bucket=self._bucket)
            return
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")
            if error_code in ("404", "NoSuchBucket", "NotFound"):
                pass
            elif error_code in ("403", "AccessDenied"):
                raise RuntimeError(
                    f"Cannot access S3 bucket {self._bucket!r}: permission denied. "
                    "Verify BLOB_S3_* credentials and bucket policy."
                ) from exc
            else:
                raise

        try:
            if self._endpoint_url or self._region == "us-east-1":
                client.create_bucket(Bucket=self._bucket)
            else:
                client.create_bucket(
                    Bucket=self._bucket,
                    CreateBucketConfiguration={"LocationConstraint": self._region},
                )
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")
            if error_code in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
                return
            raise RuntimeError(
                f"Cannot create S3 bucket {self._bucket!r}. "
                "Create it manually or grant s3:CreateBucket on this principal."
            ) from exc

    def _object_exists(self, key: str) -> bool:
        try:
            self._s3.head_object(Bucket=self._bucket, Key=key)
            return True
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")
            if error_code in ("404", "NoSuchKey", "NotFound"):
                return False
            raise

    def _put_object(self, key: str, data: bytes) -> None:
        self._s3.put_object(Bucket=self._bucket, Key=key, Body=data)

    def _get_object(self, key: str, digest: str) -> bytes:
        try:
            response = self._s3.get_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")
            if error_code in ("404", "NoSuchKey", "NotFound"):
                raise FileNotFoundError(digest) from exc
            raise
        body = response["Body"].read()
        return body

    async def put_blob(self, data: bytes) -> str:
        digest = blob_digest(data)
        key = blob_object_key(digest)
        if not await asyncio.to_thread(self._object_exists, key):
            await asyncio.to_thread(self._put_object, key, data)
        return digest

    async def get_blob(self, digest: str) -> bytes:
        key = blob_object_key(digest)
        return await asyncio.to_thread(self._get_object, key, digest)

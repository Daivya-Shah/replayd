"""Test helpers for filesystem and optional S3 blob backends."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import boto3
import pytest
from botocore.exceptions import ClientError

from replayd.storage.blob_store import BlobStore
from replayd.storage.blobs import FilesystemBlobStore
from replayd.storage.s3_blobs import S3BlobStore

S3_TEST_ENDPOINT_URL = os.environ.get("REPLAYD_TEST_S3_ENDPOINT_URL")
S3_TEST_ACCESS_KEY_ID = os.environ.get("REPLAYD_TEST_S3_ACCESS_KEY_ID")
S3_TEST_SECRET_ACCESS_KEY = os.environ.get("REPLAYD_TEST_S3_SECRET_ACCESS_KEY")
S3_TEST_REGION = os.environ.get("REPLAYD_TEST_S3_REGION", "us-east-1")


def s3_blob_testing_enabled() -> bool:
    return bool(
        S3_TEST_ENDPOINT_URL
        and S3_TEST_ACCESS_KEY_ID
        and S3_TEST_SECRET_ACCESS_KEY
    )


def blob_store_params() -> list[pytest.ParameterSet]:
    params: list[pytest.ParameterSet] = [pytest.param("filesystem", id="filesystem")]
    if s3_blob_testing_enabled():
        params.append(pytest.param("s3", id="s3"))
    return params


def _s3_client():
    return boto3.client(
        "s3",
        endpoint_url=S3_TEST_ENDPOINT_URL,
        aws_access_key_id=S3_TEST_ACCESS_KEY_ID,
        aws_secret_access_key=S3_TEST_SECRET_ACCESS_KEY,
        region_name=S3_TEST_REGION,
    )


def _create_s3_test_bucket() -> str:
    bucket_name = f"test-{uuid.uuid4().hex}"
    client = _s3_client()
    client.create_bucket(Bucket=bucket_name)
    return bucket_name


def _delete_s3_test_bucket(bucket_name: str) -> None:
    client = _s3_client()
    try:
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket_name):
            objects = page.get("Contents", [])
            if objects:
                client.delete_objects(
                    Bucket=bucket_name,
                    Delete={"Objects": [{"Key": obj["Key"]} for obj in objects]},
                )
        client.delete_bucket(Bucket=bucket_name)
    except ClientError:
        pass


async def open_blob_store(
    backend: str,
    tmp_path: Path,
) -> tuple[BlobStore, str | None]:
    if backend == "filesystem":
        store = FilesystemBlobStore(str(tmp_path))
        await store.init()
        return store, None

    bucket_name = _create_s3_test_bucket()
    store = S3BlobStore(
        bucket=bucket_name,
        region=S3_TEST_REGION,
        endpoint_url=S3_TEST_ENDPOINT_URL,
        access_key_id=S3_TEST_ACCESS_KEY_ID,
        secret_access_key=S3_TEST_SECRET_ACCESS_KEY,
    )
    await store.init()
    return store, bucket_name


async def close_blob_store(
    store: BlobStore,
    backend: str,
    bucket_name: str | None,
) -> None:
    await store.aclose()
    if backend == "s3" and bucket_name is not None:
        _delete_s3_test_bucket(bucket_name)

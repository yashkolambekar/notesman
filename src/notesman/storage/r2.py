import asyncio
from functools import lru_cache
from typing import BinaryIO

import boto3
from botocore.config import Config
from fastapi import HTTPException

from notesman.core.config import Settings, get_settings


class R2Storage:
    """Thin async wrapper over the S3 API. boto3 is blocking, so calls run in a thread."""

    def __init__(self, s: Settings):
        self.bucket = s.r2_bucket
        self._c = boto3.client(
            "s3",
            endpoint_url=f"https://{s.r2_account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=s.r2_access_key_id,
            aws_secret_access_key=s.r2_secret_access_key,
            region_name="auto",
            config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
        )

    async def put(self, key: str, fileobj: BinaryIO, content_type: str | None) -> None:
        extra = {"ContentType": content_type} if content_type else {}
        await asyncio.to_thread(self._c.upload_fileobj, fileobj, self.bucket, key, ExtraArgs=extra)

    async def put_bytes(self, key: str, data: bytes, content_type: str | None = None) -> None:
        extra = {"ContentType": content_type} if content_type else {}
        await asyncio.to_thread(self._c.put_object, Bucket=self.bucket, Key=key, Body=data, **extra)

    async def get(self, key: str) -> bytes:
        res = await asyncio.to_thread(self._c.get_object, Bucket=self.bucket, Key=key)
        return await asyncio.to_thread(res["Body"].read)

    async def delete_prefix(self, prefix: str) -> int:
        def run() -> int:
            n = 0
            for page in self._c.get_paginator("list_objects_v2").paginate(
                Bucket=self.bucket, Prefix=prefix
            ):
                keys = [{"Key": o["Key"]} for o in page.get("Contents", [])]
                if keys:
                    self._c.delete_objects(Bucket=self.bucket, Delete={"Objects": keys})
                    n += len(keys)
            return n

        return await asyncio.to_thread(run)


@lru_cache
def _storage() -> R2Storage:
    return R2Storage(get_settings())


def r2_configured() -> bool:
    s = get_settings()
    return all([s.r2_account_id, s.r2_access_key_id, s.r2_secret_access_key, s.r2_bucket])


def get_storage_optional() -> R2Storage | None:
    """For cleanup paths: deleting a record must still work if R2 is not configured."""
    return _storage() if r2_configured() else None


def get_storage() -> R2Storage:
    if not r2_configured():
        raise HTTPException(503, "File storage (R2) is not configured")
    return _storage()

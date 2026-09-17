"""Object storage for the evidence store (A-TO-Z-PLAN.md §F.4).

Raw HTML / DOM / screenshots / SERP+AI payloads go here, content-addressed and immutable.
Keys are prefixed `tenant/{tid}/project/{pid}/...` so tenant isolation holds at the storage
layer too (§F.2). S3-compatible: MinIO in dev, R2/S3 in prod."""

from __future__ import annotations

import gzip
from functools import lru_cache
from typing import Any

import boto3
from botocore.config import Config

from common.settings import settings


@lru_cache
def _client() -> Any:
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint or None,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
        region_name="auto",
    )


def key_for(tenant_id: str, project_id: str, kind: str, content_hash: str, ext: str = "gz") -> str:
    return f"tenant/{tenant_id}/project/{project_id}/{kind}/{content_hash}.{ext}"


def put_text(key: str, text: str, *, compress: bool = True) -> str:
    body = gzip.compress(text.encode("utf-8")) if compress else text.encode("utf-8")
    _client().put_object(
        Bucket=settings.s3_bucket,
        Key=key,
        Body=body,
        ContentType="text/html; charset=utf-8",
        ContentEncoding="gzip" if compress else "identity",
    )
    return key


def get_text(key: str) -> str:
    obj = _client().get_object(Bucket=settings.s3_bucket, Key=key)
    raw: bytes = obj["Body"].read()
    if obj.get("ContentEncoding") == "gzip" or key.endswith(".gz"):
        raw = gzip.decompress(raw)
    return raw.decode("utf-8")


def ensure_bucket() -> None:
    """Idempotent — used by dev setup and tests."""
    c = _client()
    try:
        c.head_bucket(Bucket=settings.s3_bucket)
    except Exception:  # noqa: BLE001
        c.create_bucket(Bucket=settings.s3_bucket)

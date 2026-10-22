from functools import lru_cache

import boto3
from botocore.config import Config

from app.core.config import get_settings


@lru_cache
def _client():
    settings = get_settings()
    if not settings.neon_storage_endpoint:
        raise RuntimeError("NEON_STORAGE_ENDPOINT is not set")
    return boto3.client(
        "s3",
        endpoint_url=settings.neon_storage_endpoint,
        region_name=settings.neon_storage_region,
        aws_access_key_id=settings.neon_storage_access_key,
        aws_secret_access_key=settings.neon_storage_secret_key,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},  # Neon requires path-style URLs
            # Recent SDKs embed a checksum computed from an empty body in presigned
            # PUT URLs, which rejects real uploads. Only compute one when required.
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        ),
    )


def upload_bytes(key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    """Store a file and return its object key."""
    _client().put_object(
        Bucket=get_settings().neon_storage_bucket, Key=key, Body=data, ContentType=content_type
    )
    return key


def download_bytes(key: str) -> bytes:
    response = _client().get_object(Bucket=get_settings().neon_storage_bucket, Key=key)
    return response["Body"].read()


def delete_object(key: str) -> None:
    _client().delete_object(Bucket=get_settings().neon_storage_bucket, Key=key)


def presigned_url(key: str, expires_in: int = 900, method: str = "get_object") -> str:
    """A time-limited URL for downloading ("get_object") or uploading ("put_object")."""
    return _client().generate_presigned_url(
        method,
        Params={"Bucket": get_settings().neon_storage_bucket, "Key": key},
        ExpiresIn=expires_in,
    )

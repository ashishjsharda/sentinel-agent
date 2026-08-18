"""S3-backed storage for larger agent artifacts (diagnosis reports, diffs).

CockroachDB holds the pointer (resolutions.artifact_s3_key); S3 holds the
blob. Keeps the database lean while still giving the agent a durable place
to write longer-form output.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

import boto3

from .config import settings

logger = logging.getLogger("sentinel.artifacts")

_s3 = None


def _client():
    global _s3
    if _s3 is None:
        _s3 = boto3.client("s3", region_name=settings.aws_region)
    return _s3


def put_report(incident_id: UUID, report_text: str) -> str:
    """Upload a text report to S3 and return its object key."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    key = f"incidents/{incident_id}/{timestamp}-report.md"
    _client().put_object(
        Bucket=settings.s3_bucket,
        Key=key,
        Body=report_text.encode("utf-8"),
        ContentType="text/markdown",
    )
    logger.info("wrote artifact s3://%s/%s", settings.s3_bucket, key)
    return key


def get_report(key: str) -> str:
    obj = _client().get_object(Bucket=settings.s3_bucket, Key=key)
    return obj["Body"].read().decode("utf-8")

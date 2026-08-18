"""Central configuration, loaded from environment variables (.env in local dev)."""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _require(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None:
        raise RuntimeError(
            f"Missing required environment variable {name!r}. "
            f"Copy .env.example to .env and fill it in."
        )
    return value


@dataclass(frozen=True)
class Settings:
    database_url: str
    aws_region: str
    bedrock_reasoning_model_id: str
    bedrock_embedding_model_id: str
    s3_bucket: str
    vector_dim: int
    log_level: str


def load_settings() -> Settings:
    return Settings(
        database_url=_require("DATABASE_URL"),
        aws_region=os.environ.get("AWS_REGION", "us-east-1"),
        bedrock_reasoning_model_id=os.environ.get(
            "BEDROCK_REASONING_MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0"
        ),
        bedrock_embedding_model_id=os.environ.get(
            "BEDROCK_EMBEDDING_MODEL_ID", "amazon.titan-embed-text-v2:0"
        ),
        s3_bucket=os.environ.get("SENTINEL_S3_BUCKET", "sentinel-agent-artifacts"),
        vector_dim=int(os.environ.get("SENTINEL_VECTOR_DIM", "1024")),
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
    )


settings = load_settings()

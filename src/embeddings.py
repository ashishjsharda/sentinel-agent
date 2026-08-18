"""Text embeddings via Amazon Bedrock (Titan Text Embeddings v2).

These embeddings are written into CockroachDB's `incident_embeddings.embedding`
VECTOR column and queried with CockroachDB's Distributed Vector Indexing for
semantic recall of past incidents -- this is one of the two required
CockroachDB tools this project uses.
"""
from __future__ import annotations

import json
import logging
from typing import List

import boto3

from .config import settings

logger = logging.getLogger("sentinel.embeddings")

_bedrock_runtime = None


def _client():
    global _bedrock_runtime
    if _bedrock_runtime is None:
        _bedrock_runtime = boto3.client("bedrock-runtime", region_name=settings.aws_region)
    return _bedrock_runtime


def embed_text(text: str) -> List[float]:
    """Return an embedding vector for `text` using the configured Bedrock
    embedding model (default: amazon.titan-embed-text-v2:0, 1024 dims).
    """
    body = json.dumps({"inputText": text[:8000], "dimensions": settings.vector_dim})
    response = _client().invoke_model(
        modelId=settings.bedrock_embedding_model_id,
        body=body,
        contentType="application/json",
        accept="application/json",
    )
    payload = json.loads(response["body"].read())
    embedding = payload.get("embedding")
    if not embedding:
        raise RuntimeError(f"Bedrock embedding response missing 'embedding': {payload}")
    return embedding


def to_pgvector_literal(vector: List[float]) -> str:
    """Format a Python list of floats as a CockroachDB/pgvector literal,
    e.g. '[0.01,-0.22,0.9]'.
    """
    return "[" + ",".join(f"{v:.8f}" for v in vector) + "]"

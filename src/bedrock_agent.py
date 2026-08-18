"""Reasoning model access via Amazon Bedrock (Claude).

This is the "brain" of the agent: given the current incident, the semantic
memory of similar past incidents (retrieved from CockroachDB), and the
conversation-so-far (also from CockroachDB), it decides what to do next.
"""
from __future__ import annotations

import json
import logging
from typing import List, TypedDict

import boto3

from .config import settings

logger = logging.getLogger("sentinel.bedrock_agent")

_bedrock_runtime = None

SYSTEM_PROMPT = """You are Sentinel, an autonomous DevOps/incident-response agent.
You are given:
  - the current incident (title, description, service, severity)
  - similar past incidents and how they were resolved (retrieved from persistent memory)
  - the conversation so far on this incident

Respond with a concise triage: a likely root cause hypothesis, the next
diagnostic or remediation step to take, and whether this looks resolvable
autonomously or needs a human. Be specific and reference the past incidents
you were shown when they are relevant. Keep it under 200 words.
"""


class Message(TypedDict):
    role: str  # "user" | "assistant"
    content: str


def _client():
    global _bedrock_runtime
    if _bedrock_runtime is None:
        _bedrock_runtime = boto3.client("bedrock-runtime", region_name=settings.aws_region)
    return _bedrock_runtime


def generate_response(messages: List[Message], system: str = SYSTEM_PROMPT) -> str:
    """Call the Bedrock-hosted Claude model with the Anthropic Messages API
    schema (Bedrock's `anthropic.claude-*` models accept this directly).
    """
    body = json.dumps(
        {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 1024,
            "system": system,
            "messages": [{"role": m["role"], "content": m["content"]} for m in messages],
        }
    )
    response = _client().invoke_model(
        modelId=settings.bedrock_reasoning_model_id,
        body=body,
        contentType="application/json",
        accept="application/json",
    )
    payload = json.loads(response["body"].read())
    content_blocks = payload.get("content", [])
    text = "".join(block.get("text", "") for block in content_blocks if block.get("type") == "text")
    if not text:
        raise RuntimeError(f"Bedrock reasoning response had no text content: {payload}")
    return text

"""The agent's persistent memory layer, backed entirely by CockroachDB.

Three kinds of memory live here, all in the same transactionally-consistent
database (no separate vector store, no consistency gaps):

  1. Structured/transactional memory -- incidents, task_state
  2. Conversational memory           -- conversation_messages
  3. Semantic memory                 -- incident_embeddings, searched via
                                         CockroachDB's Distributed Vector
                                         Indexing (cosine distance `<=>`)
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Optional
from uuid import UUID

from psycopg import Connection
from psycopg.rows import dict_row

from .db import run_in_transaction, transaction
from .embeddings import embed_text, to_pgvector_literal

logger = logging.getLogger("sentinel.memory")


# ---------------------------------------------------------------------------
# Incidents
# ---------------------------------------------------------------------------

def create_incident(
    service_name: str,
    title: str,
    description: str,
    severity: str = "medium",
    source: str = "manual",
    external_ref: Optional[str] = None,
) -> UUID:
    def _op(conn: Connection) -> UUID:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT id FROM services WHERE name = %s", (service_name,))
            row = cur.fetchone()
            if row is None:
                cur.execute(
                    "INSERT INTO services (name) VALUES (%s) RETURNING id",
                    (service_name,),
                )
                row = cur.fetchone()
            service_id = row["id"]

            cur.execute(
                """
                INSERT INTO incidents (service_id, title, description, severity, source, external_ref)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (service_id, title, description, severity, source, external_ref),
            )
            incident_id = cur.fetchone()["id"]

            cur.execute(
                """
                INSERT INTO task_state (incident_id, plan, step_index, scratchpad, status)
                VALUES (%s, '[]', 0, '{}', 'pending')
                """,
                (incident_id,),
            )
        return incident_id

    incident_id = run_in_transaction(_op)
    logger.info("created incident %s for service %s", incident_id, service_name)

    # Embed the incident and store it for future semantic recall. Done as a
    # second transaction since it calls out to Bedrock (network I/O) and we
    # don't want to hold a DB transaction open across that call.
    vector = embed_text(f"{title}\n\n{description}")
    _store_embedding(incident_id, vector, model_id="bedrock-embedding")
    return incident_id


def _store_embedding(incident_id: UUID, vector: list[float], model_id: str) -> None:
    literal = to_pgvector_literal(vector)

    def _op(conn: Connection) -> None:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPSERT INTO incident_embeddings (incident_id, embedding, embedding_model)
                VALUES (%s, %s, %s)
                """,
                (incident_id, literal, model_id),
            )

    run_in_transaction(_op)


def update_incident_status(incident_id: UUID, status: str, resolved: bool = False) -> None:
    def _op(conn: Connection) -> None:
        with conn.cursor() as cur:
            if resolved:
                cur.execute(
                    """
                    UPDATE incidents
                    SET status = %s, updated_at = now(), resolved_at = now()
                    WHERE id = %s
                    """,
                    (status, incident_id),
                )
            else:
                cur.execute(
                    "UPDATE incidents SET status = %s, updated_at = now() WHERE id = %s",
                    (status, incident_id),
                )

    run_in_transaction(_op)


def get_incident(incident_id: UUID) -> dict[str, Any]:
    def _op(conn: Connection) -> dict[str, Any]:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM incidents WHERE id = %s", (incident_id,))
            return cur.fetchone()

    return run_in_transaction(_op)


# ---------------------------------------------------------------------------
# Conversation memory
# ---------------------------------------------------------------------------

def append_message(
    incident_id: UUID,
    role: str,
    content: str,
    tool_name: Optional[str] = None,
    tool_input: Optional[dict] = None,
) -> None:
    def _op(conn: Connection) -> None:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO conversation_messages (incident_id, role, content, tool_name, tool_input)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (incident_id, role, content, tool_name, json.dumps(tool_input) if tool_input else None),
            )

    run_in_transaction(_op)


def get_conversation(incident_id: UUID, limit: int = 50) -> list[dict[str, Any]]:
    def _op(conn: Connection) -> list[dict[str, Any]]:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT role, content, tool_name, tool_input, created_at
                FROM conversation_messages
                WHERE incident_id = %s
                ORDER BY created_at ASC
                LIMIT %s
                """,
                (incident_id, limit),
            )
            return cur.fetchall()

    return run_in_transaction(_op)


# ---------------------------------------------------------------------------
# Task state (durable agent scratchpad -- survives crashes/rescheduling)
# ---------------------------------------------------------------------------

def load_task_state(incident_id: UUID) -> dict[str, Any]:
    def _op(conn: Connection) -> dict[str, Any]:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM task_state WHERE incident_id = %s", (incident_id,))
            return cur.fetchone()

    return run_in_transaction(_op)


def save_task_state(
    incident_id: UUID,
    plan: list[str],
    step_index: int,
    scratchpad: dict[str, Any],
    status: str,
) -> None:
    def _op(conn: Connection) -> None:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPSERT INTO task_state (incident_id, plan, step_index, scratchpad, status, updated_at)
                VALUES (%s, %s, %s, %s, %s, now())
                """,
                (incident_id, json.dumps(plan), step_index, json.dumps(scratchpad), status),
            )

    run_in_transaction(_op)


# ---------------------------------------------------------------------------
# Semantic memory (CockroachDB Distributed Vector Indexing)
# ---------------------------------------------------------------------------

@dataclass
class SimilarIncident:
    incident_id: UUID
    title: str
    description: str
    resolution_summary: Optional[str]
    root_cause: Optional[str]
    distance: float


def find_similar_incidents(
    query_text: str, exclude_incident_id: Optional[UUID] = None, top_k: int = 3
) -> list[SimilarIncident]:
    """Semantic search over past incidents using CockroachDB's vector index.

    Uses cosine distance (`<=>`) between the query embedding and every row
    in `incident_embeddings`; the CREATE VECTOR INDEX in db/schema.sql lets
    CockroachDB serve this as an approximate nearest-neighbor lookup that
    stays fast as the table grows, instead of a full scan.
    """
    query_vector = to_pgvector_literal(embed_text(query_text))

    def _op(conn: Connection) -> list[SimilarIncident]:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT
                    i.id AS incident_id,
                    i.title,
                    i.description,
                    r.summary AS resolution_summary,
                    r.root_cause,
                    e.embedding <=> %s AS distance
                FROM incident_embeddings e
                JOIN incidents i ON i.id = e.incident_id
                LEFT JOIN resolutions r ON r.incident_id = i.id
                WHERE (%s::UUID IS NULL OR i.id != %s)
                ORDER BY e.embedding <=> %s
                LIMIT %s
                """,
                (query_vector, exclude_incident_id, exclude_incident_id, query_vector, top_k),
            )
            return [SimilarIncident(**row) for row in cur.fetchall()]

    return run_in_transaction(_op)


# ---------------------------------------------------------------------------
# Resolutions
# ---------------------------------------------------------------------------

def record_resolution(
    incident_id: UUID,
    summary: str,
    root_cause: Optional[str] = None,
    fix_description: Optional[str] = None,
    artifact_s3_key: Optional[str] = None,
) -> None:
    def _op(conn: Connection) -> None:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPSERT INTO resolutions (incident_id, summary, root_cause, fix_description, artifact_s3_key)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (incident_id, summary, root_cause, fix_description, artifact_s3_key),
            )

    run_in_transaction(_op)
    update_incident_status(incident_id, "resolved", resolved=True)


# re-export for convenience
__all__ = [
    "create_incident",
    "update_incident_status",
    "get_incident",
    "append_message",
    "get_conversation",
    "load_task_state",
    "save_task_state",
    "find_similar_incidents",
    "record_resolution",
    "SimilarIncident",
    "transaction",
]

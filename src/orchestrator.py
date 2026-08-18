"""The agent loop: ties CockroachDB memory + Bedrock reasoning together.

Flow for one incident:
  1. Load (or create) durable task_state and conversation history from
     CockroachDB -- so a fresh Lambda invocation resumes exactly where a
     prior one left off.
  2. Semantic recall: search incident_embeddings via CockroachDB's vector
     index for similar past incidents + how they were resolved.
  3. Build a prompt from (current incident + similar incidents +
     conversation so far) and call Bedrock (Claude) for the next step.
  4. Persist the assistant's response back into conversation_messages and
     task_state -- atomically, so memory never has a "gap".
  5. Optionally write a longer report to S3 and store the pointer.
"""
from __future__ import annotations

import logging
from uuid import UUID

from . import memory
from .artifacts import put_report
from .bedrock_agent import Message, generate_response

logger = logging.getLogger("sentinel.orchestrator")


def _format_similar_incidents(similar: list[memory.SimilarIncident]) -> str:
    if not similar:
        return "No similar past incidents found in memory."
    lines = ["Similar past incidents (from CockroachDB semantic memory):"]
    for s in similar:
        lines.append(
            f"- [{s.distance:.3f} distance] \"{s.title}\": {s.description[:200]}\n"
            f"  Resolution: {s.resolution_summary or 'unresolved'} "
            f"(root cause: {s.root_cause or 'unknown'})"
        )
    return "\n".join(lines)


def run_step(incident_id: UUID, human_input: str | None = None) -> str:
    """Advance the agent by one step on the given incident. Returns the
    assistant's response text. Safe to call repeatedly / from any process --
    all state needed to resume lives in CockroachDB.
    """
    incident = memory.get_incident(incident_id)
    state = memory.load_task_state(incident_id)
    history = memory.get_conversation(incident_id)

    if human_input:
        memory.append_message(incident_id, role="user", content=human_input)
        history.append({"role": "user", "content": human_input})

    similar = memory.find_similar_incidents(
        f"{incident['title']}\n{incident['description']}",
        exclude_incident_id=incident_id,
        top_k=3,
    )

    context_prefix = (
        f"Incident: {incident['title']} (severity={incident['severity']}, "
        f"status={incident['status']})\n"
        f"Description: {incident['description']}\n\n"
        f"{_format_similar_incidents(similar)}\n"
    )

    messages: list[Message] = [{"role": "user", "content": context_prefix}]
    for turn in history:
        role = "assistant" if turn["role"] == "assistant" else "user"
        messages.append({"role": role, "content": turn["content"]})
    if not history:
        messages.append({"role": "user", "content": "Begin triage."})

    response_text = generate_response(messages)

    memory.append_message(incident_id, role="assistant", content=response_text)

    new_step_index = state["step_index"] + 1
    plan = state["plan"] if isinstance(state["plan"], list) else []
    scratchpad = state["scratchpad"] if isinstance(state["scratchpad"], dict) else {}
    scratchpad[f"step_{new_step_index}"] = response_text[:500]

    looks_resolved = "resolved" in response_text.lower()[:400]
    new_status = "done" if looks_resolved else "running"
    memory.save_task_state(
        incident_id,
        plan=plan,
        step_index=new_step_index,
        scratchpad=scratchpad,
        status=new_status,
    )
    memory.update_incident_status(
        incident_id, "resolved" if looks_resolved else "investigating", resolved=looks_resolved
    )

    if looks_resolved:
        report = (
            f"# Incident Report: {incident['title']}\n\n"
            f"## Description\n{incident['description']}\n\n"
            f"## Agent Resolution\n{response_text}\n\n"
            f"## Similar Past Incidents Consulted\n{_format_similar_incidents(similar)}\n"
        )
        s3_key = put_report(incident_id, report)
        memory.record_resolution(
            incident_id,
            summary=response_text[:500],
            fix_description=response_text,
            artifact_s3_key=s3_key,
        )

    return response_text

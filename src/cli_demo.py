"""Local demo: exercises the full memory + reasoning loop from the command
line against a real CockroachDB cluster + AWS Bedrock, without deploying
anything to Lambda first. This is what the <3 min submission video should
walk through.

Usage:
    python -m src.cli_demo seed          # create a couple of past, resolved incidents
    python -m src.cli_demo new           # file a new incident and watch the agent triage it
    python -m src.cli_demo chat <id>     # continue the conversation on an existing incident
"""
from __future__ import annotations

import sys
from uuid import UUID

from . import memory
from .orchestrator import run_step

DEMO_SERVICE = "demo-checkout-service"


def seed() -> None:
    """Create two already-resolved incidents so semantic search has
    something relevant to find when a new, similar incident comes in.
    """
    print("Seeding past incidents into CockroachDB memory...")

    id1 = memory.create_incident(
        service_name=DEMO_SERVICE,
        title="Checkout service 5xx spike after deploy",
        description=(
            "Error rate on POST /checkout jumped to 40% within 5 minutes of "
            "deploying v2.14.0. Logs show 'connection pool exhausted' errors "
            "against the payments DB."
        ),
        severity="high",
        source="cloudwatch",
    )
    memory.record_resolution(
        id1,
        summary="Rolled back v2.14.0; root cause was a missing DB pool size override.",
        root_cause="New connection-per-request code path bypassed the shared pool.",
        fix_description=(
            "Reverted deploy, then re-released with the pool override applied "
            "via the config service before the pooled client was instantiated."
        ),
    )
    print(f"  seeded incident {id1} (resolved)")

    id2 = memory.create_incident(
        service_name=DEMO_SERVICE,
        title="Checkout latency p99 regression",
        description=(
            "p99 latency on /checkout went from 180ms to 1.4s starting ~14:00 UTC. "
            "No recent deploy. CPU on checkout pods is normal."
        ),
        severity="medium",
        source="cloudwatch",
    )
    memory.record_resolution(
        id2,
        summary="Downstream inventory service was throttling us; added a circuit breaker.",
        root_cause="Inventory service rate limit was lowered during a capacity migration.",
        fix_description="Added a circuit breaker + cache fallback for inventory lookups.",
    )
    print(f"  seeded incident {id2} (resolved)")
    print("Done. These will surface via CockroachDB vector search on the next 'new' incident.")


def new_incident() -> None:
    print("Filing a new incident...")
    incident_id = memory.create_incident(
        service_name=DEMO_SERVICE,
        title="Checkout service returning 500s after latest release",
        description=(
            "Started seeing elevated 500 errors on /checkout right after this "
            "morning's deploy. Error logs mention the payments DB connection pool."
        ),
        severity="high",
        source="cli_demo",
    )
    print(f"Created incident {incident_id}")
    print("Running first agent step (semantic recall + Bedrock triage)...\n")
    response = run_step(incident_id)
    print("--- Agent response ---")
    print(response)
    print(f"\nIncident id for follow-up: {incident_id}")


def chat(incident_id_str: str) -> None:
    incident_id = UUID(incident_id_str)
    human_input = input("You: ")
    response = run_step(incident_id, human_input=human_input)
    print("\n--- Agent response ---")
    print(response)


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1]
    if command == "seed":
        seed()
    elif command == "new":
        new_incident()
    elif command == "chat":
        if len(sys.argv) < 3:
            print("usage: python -m src.cli_demo chat <incident_id>")
            sys.exit(1)
        chat(sys.argv[2])
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()

"""AWS Lambda entrypoint.

Deployed behind a Lambda Function URL (or API Gateway) via deploy/template.yaml.
Two ways to invoke:

  1. Direct Lambda event (e.g. from an EventBridge rule watching CloudWatch
     alarms, or a PagerDuty/GitHub webhook via API Gateway):
        {"action": "create_incident", "service": "...", "title": "...", "description": "..."}
        {"action": "step", "incident_id": "...", "human_input": "optional"}

  2. HTTP via API Gateway / Function URL, using the same JSON body shape,
     POSTed to the function URL.

Kept dependency-light (no FastAPI/Mangum needed) since the payload shape is
simple JSON in, JSON out -- this also makes it trivial to test locally with
`python -c "from src.lambda_handler import handler; ..."`.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from . import memory
from .orchestrator import run_step

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sentinel.lambda")


def _parse_event_body(event: dict[str, Any]) -> dict[str, Any]:
    # Direct Lambda invocation: the event *is* the payload.
    if "action" in event:
        return event
    # API Gateway / Function URL: payload is JSON-encoded in "body".
    body = event.get("body")
    if body is None:
        raise ValueError("No 'action' key and no 'body' in event; nothing to do.")
    if event.get("isBase64Encoded"):
        import base64

        body = base64.b64decode(body).decode("utf-8")
    return json.loads(body)


def _response(status_code: int, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(payload, default=str),
    }


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    try:
        payload = _parse_event_body(event)
        action = payload.get("action")

        if action == "create_incident":
            incident_id = memory.create_incident(
                service_name=payload["service"],
                title=payload["title"],
                description=payload["description"],
                severity=payload.get("severity", "medium"),
                source=payload.get("source", "api"),
                external_ref=payload.get("external_ref"),
            )
            response_text = run_step(incident_id)
            return _response(
                200, {"incident_id": str(incident_id), "agent_response": response_text}
            )

        if action == "step":
            incident_id = payload["incident_id"]
            response_text = run_step(incident_id, human_input=payload.get("human_input"))
            return _response(200, {"incident_id": incident_id, "agent_response": response_text})

        if action == "get_incident":
            incident_id = payload["incident_id"]
            incident = memory.get_incident(incident_id)
            conversation = memory.get_conversation(incident_id)
            return _response(200, {"incident": incident, "conversation": conversation})

        return _response(400, {"error": f"Unknown action: {action!r}"})

    except Exception as exc:  # noqa: BLE001 - top-level Lambda error boundary
        logger.exception("sentinel lambda handler failed")
        return _response(500, {"error": str(exc)})

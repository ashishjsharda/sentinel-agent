# Sentinel — a DevOps agent whose memory never goes down

Built for the 🪳 CockroachDB × AWS Hackathon.

Sentinel is an incident-triage agent: it ingests incidents (from an alert,
a webhook, or the CLI demo), searches its own memory of similar past
incidents, reasons about a fix with an LLM, and remembers the whole
conversation and its own task progress durably — all in **CockroachDB**,
deployed on **AWS**.

> **Status**: scaffolded and ready to configure. This repo does not ship
> with live CockroachDB/AWS credentials — see [Setup](#setup) to provision
> your own cluster and Bedrock access, then run the demo end-to-end.

## Why this matters

Traditional agent demos keep memory in a Python dict or a local file. That
falls over the moment the process restarts, scales to two instances, or a
cloud region blips. Sentinel's memory — conversation history, task
progress, and semantic recall of past incidents — lives in CockroachDB, so
it survives crashes, retries, and failover with zero data loss. See
[`docs/architecture.md`](docs/architecture.md) for the full design and a
diagram.

## What it does

1. An incident comes in (`create_incident`).
2. Sentinel embeds the incident text and searches CockroachDB's
   **Distributed Vector Indexing** for similar past incidents and how they
   were resolved.
3. It sends the incident + retrieved memories + conversation history to
   **Amazon Bedrock** (Claude) for a triage decision.
4. The response, updated task state, and (optionally) a full S3-hosted
   report are all written back to CockroachDB in a transaction.
5. Any later invocation — a retry, a follow-up question, a totally
   different Lambda cold start — resumes from exactly what's in the
   database. Nothing lives only in memory.

## CockroachDB tools used

| Tool | Where | What it does here |
|---|---|---|
| **Distributed Vector Indexing** | `db/schema.sql` (`incident_embeddings`, `CREATE VECTOR INDEX`), `src/memory.py::find_similar_incidents` | Semantic recall of similar past incidents + resolutions |
| **Cloud Managed MCP Server** | `mcp/mcp_config.example.json` | Lets Claude Code / Cursor inspect the live memory store during development, read-only + audit-logged |
| **Agent Skills Repo** | `skills/README.md` | Guided schema design (indexing, vector index syntax, retry semantics) |
| **ccloud CLI** | `deploy/deploy.sh --provision-db` | Non-interactive cluster provisioning + connection string retrieval |

(Two are required; this project uses all four.)

## AWS services used

| Service | Where | What it does here |
|---|---|---|
| **Amazon Bedrock** | `src/bedrock_agent.py`, `src/embeddings.py` | Claude for reasoning, Titan Text Embeddings v2 for vectors |
| **AWS Lambda** | `src/lambda_handler.py`, `deploy/template.yaml` | Serverless execution of the whole agent step |
| **Amazon S3** | `src/artifacts.py` | Stores full incident reports; CockroachDB keeps the pointer |

## Repo layout

```
db/schema.sql            CockroachDB schema: incidents, task_state,
                          conversation_messages, incident_embeddings (+ vector
                          index), resolutions
src/config.py             env-based settings
src/db.py                 connection + CockroachDB-aware transaction retry
src/embeddings.py         Bedrock Titan embeddings -> pgvector literal
src/bedrock_agent.py      Bedrock Claude reasoning calls
src/memory.py             all persistence: incidents, task_state,
                          conversation, vector search, resolutions
src/artifacts.py          S3 report storage
src/orchestrator.py       the agent loop (ties memory + reasoning together)
src/lambda_handler.py     AWS Lambda entrypoint
src/cli_demo.py           local demo CLI (seed / new / chat)
mcp/mcp_config.example.json   CockroachDB Cloud Managed MCP Server config
skills/README.md          CockroachDB Agent Skills Repo usage notes
deploy/template.yaml      AWS SAM template (Lambda + S3 + IAM)
deploy/deploy.sh          provisions DB (optional) + deploys to AWS
docs/architecture.md      design doc + mermaid diagram
docs/demo_script.md       <3 min video outline
tests/test_memory.py      unit tests for pure helpers
```

## Setup

### 1. CockroachDB Cloud

1. Create a free cluster at [cockroachlabs.cloud](https://cockroachlabs.cloud).
2. Grab the connection string from **Connect** and put it in `.env` as
   `DATABASE_URL` (copy `.env.example` to `.env` first).
3. Apply the schema:
   ```bash
   cockroach sql --url "$DATABASE_URL" -f db/schema.sql
   ```
   (Or paste the contents of `db/schema.sql` into the Cloud Console's SQL
   shell.)
4. Optional — set up the **Managed MCP Server** so Claude Code/Cursor can
   query your cluster directly: Cloud Console → your cluster → **MCP** →
   generate an API key, then fill in `mcp/mcp_config.example.json` and
   point your MCP client at it.
5. Optional — install the `ccloud` CLI and run `ccloud auth login` if you
   want to provision the cluster from the command line instead
   (`deploy/deploy.sh --provision-db`).

### 2. AWS / Bedrock

1. In the Bedrock console, enable model access for
   `anthropic.claude-3-5-sonnet-20241022-v2:0` and
   `amazon.titan-embed-text-v2:0` (or your preferred equivalents — update
   `.env` if you use different model IDs).
2. Configure AWS credentials locally (`aws configure` or an existing
   profile) with permission to call `bedrock:InvokeModel`.
3. Create an S3 bucket for artifacts (or let `deploy/template.yaml` create
   one for you) and set `SENTINEL_S3_BUCKET` in `.env`.

### 3. Python environment

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in DATABASE_URL, AWS_REGION, etc.
```

## Running the demo locally

```bash
python -m src.cli_demo seed   # writes 2 resolved "past" incidents + embeddings
python -m src.cli_demo new    # files a new, similar incident and triages it
python -m src.cli_demo chat <incident_id>   # continue the conversation
```

Watch the `new` command's output reference the seeded incident's root cause
— that's the CockroachDB vector index doing semantic recall, not anything
hardcoded in the prompt.

## Deploying to AWS Lambda

```bash
./deploy/deploy.sh
```

This applies the schema (if `cockroach` CLI is available), builds with AWS
SAM, and deploys `src/lambda_handler.py` behind a Lambda Function URL. Wire
a webhook (GitHub, PagerDuty, CloudWatch Alarms → EventBridge → Lambda) to
call it with:

```json
{"action": "create_incident", "service": "checkout", "title": "...", "description": "..."}
```

or continue an existing one with `{"action": "step", "incident_id": "...", "human_input": "..."}`.

## Testing

```bash
pip install pytest
pytest tests/
```

`tests/test_memory.py` covers pure helpers without needing a live cluster.
Because CockroachDB's vector index behavior isn't meaningfully mockable,
integration testing (`find_similar_incidents` actually returning sane
results) is best done via `cli_demo.py seed` + `new` against a real
cluster — see the demo steps above.

## Submission checklist

- [ ] Public repo with this README, MIT `LICENSE` (already included, visible
      in GitHub's "About" section once pushed)
- [ ] Live/functional demo app URL (deploy via `deploy/deploy.sh`, or record
      the CLI demo if you're not standing up a public endpoint)
- [ ] Demo video (<3 min, YouTube/Vimeo, public) — script in
      [`docs/demo_script.md`](docs/demo_script.md)
- [ ] CockroachDB tools used + how — see table above
- [ ] AWS services used + how — see table above
- [ ] Architecture diagram — [`docs/architecture.md`](docs/architecture.md)
      (optional but included)

## Future work

- Expose the CockroachDB Agent Skills Repo to the *running* agent (not just
  used at dev-time) via an MCP resource, so it can self-correct its own
  query patterns.
- Add a LangChain wrapper around `src/memory.py` + `src/bedrock_agent.py`
  so Sentinel can be dropped into existing LangChain agent graphs.
- Multi-tenant `services` isolation via CockroachDB row-level security once
  this moves beyond a single-team demo.

## License

MIT — see [`LICENSE`](LICENSE).

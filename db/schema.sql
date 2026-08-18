-- Sentinel Agent - CockroachDB schema
--
-- This is the persistent memory layer for the agent. It stores:
--   1. Structured transactional state   (services, incidents, task_state)
--   2. Long-term semantic memory        (incident_embeddings, via CockroachDB
--      Distributed Vector Indexing)
--   3. Conversational memory            (conversation_messages)
--
-- Requires CockroachDB v24.3+ (vector type + vector indexes). Tested against
-- CockroachDB Cloud Serverless/Dedicated.
--
-- Run with:
--   cockroach sql --url "$DATABASE_URL" -f db/schema.sql
-- or via the CockroachDB Cloud Managed MCP Server / ccloud CLI during setup.

CREATE DATABASE IF NOT EXISTS sentinel;
SET DATABASE = sentinel;

-- ---------------------------------------------------------------------------
-- Services the agent is responsible for (repos, pipelines, prod services).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS services (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        STRING NOT NULL UNIQUE,
    repo_url    STRING,
    metadata    JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Incidents / tasks the agent works on. This is the durable "case file" --
-- an agent process can crash or be rescheduled onto another Lambda
-- invocation entirely and resume exactly where it left off by reading this
-- row plus task_state and conversation_messages below.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS incidents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    service_id      UUID NOT NULL REFERENCES services(id),
    title           STRING NOT NULL,
    description     STRING NOT NULL,
    severity        STRING NOT NULL CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    status          STRING NOT NULL DEFAULT 'open'
                        CHECK (status IN ('open', 'investigating', 'awaiting_human', 'resolved', 'wont_fix')),
    source          STRING NOT NULL DEFAULT 'manual', -- e.g. 'github_issue', 'pagerduty', 'cloudwatch', 'manual'
    external_ref    STRING,                            -- e.g. GitHub issue URL / alert ID
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at     TIMESTAMPTZ,
    INDEX idx_incidents_service_status (service_id, status)
);

-- ---------------------------------------------------------------------------
-- Agent task state: the durable "scratchpad" / plan for an in-flight
-- incident. Every agent step reads-modifies-writes this row inside a
-- transaction, so memory survives process restarts, retries, and failover
-- with zero data loss -- the core requirement of "agentic memory".
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS task_state (
    incident_id     UUID PRIMARY KEY REFERENCES incidents(id),
    plan            JSONB NOT NULL DEFAULT '[]',   -- ordered list of planned steps
    step_index      INT NOT NULL DEFAULT 0,
    scratchpad       JSONB NOT NULL DEFAULT '{}',   -- arbitrary working memory (tool outputs, hypotheses)
    status          STRING NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'running', 'blocked', 'done', 'failed')),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Conversation memory: full multi-turn transcript per incident (agent
-- reasoning, tool calls/results, human messages). This is what lets the
-- agent "remember" prior turns across invocations instead of starting cold.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS conversation_messages (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id     UUID NOT NULL REFERENCES incidents(id),
    role            STRING NOT NULL CHECK (role IN ('user', 'assistant', 'tool', 'system')),
    content         STRING NOT NULL,
    tool_name       STRING,
    tool_input      JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    INDEX idx_conversation_incident_created (incident_id, created_at)
);

-- ---------------------------------------------------------------------------
-- Semantic memory: embeddings of past incidents + their resolutions, so the
-- agent can retrieve "what did we do last time something like this
-- happened" via CockroachDB's Distributed Vector Indexing instead of
-- maintaining a separate vector store.
--
-- Vector dimension defaults to 1024 to match Amazon Titan Text Embeddings
-- v2 (Bedrock). Adjust SENTINEL_VECTOR_DIM / this column if you swap models.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS incident_embeddings (
    incident_id     UUID PRIMARY KEY REFERENCES incidents(id),
    embedding       VECTOR(1024) NOT NULL,
    embedding_model STRING NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Distributed vector index for fast approximate nearest-neighbor search
-- over incident embeddings, scaling horizontally with the cluster.
CREATE VECTOR INDEX IF NOT EXISTS idx_incident_embeddings_ann
    ON incident_embeddings (embedding);

-- ---------------------------------------------------------------------------
-- Resolutions: the durable outcome of an incident, including a pointer to
-- any larger artifact (diagnosis report, patch diff) stored in S3.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS resolutions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id     UUID NOT NULL UNIQUE REFERENCES incidents(id),
    summary         STRING NOT NULL,
    root_cause      STRING,
    fix_description STRING,
    artifact_s3_key STRING,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Seed a demo service so cli_demo.py has something to attach incidents to.
INSERT INTO services (name, repo_url, metadata)
VALUES ('demo-checkout-service', 'https://github.com/example-org/checkout-service', '{"language": "python"}')
ON CONFLICT (name) DO NOTHING;

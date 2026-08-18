# Demo video script (target: under 3 minutes)

Upload to YouTube or Vimeo, set to Public, and link it in the submission.

## 0:00 - 0:20 — Hook + what this is
- "This is Sentinel: an AI DevOps agent whose memory never goes down,
  because it lives entirely in CockroachDB."
- One sentence on the problem: agents that lose memory on failover just
  stop being useful in production.

## 0:20 - 0:50 — Architecture (show `docs/architecture.md` diagram)
- Point at the three CockroachDB tools used: Managed MCP Server (dev-time
  inspection), Distributed Vector Indexing (semantic recall), Agent Skills
  Repo (schema design).
- Point at AWS: Bedrock (Claude + Titan embeddings) and Lambda (serverless
  execution), S3 for reports.

## 0:50 - 1:30 — Live demo, part 1: seeding memory
- Run `python -m src.cli_demo seed` in a terminal.
- Narrate: "This writes two already-resolved incidents into CockroachDB --
  a connection-pool exhaustion bug and a latency regression -- along with
  their embeddings."
- Optionally show the rows via `cockroach sql` or the CockroachDB Cloud
  Console SQL shell: `SELECT title, status FROM incidents;`

## 1:30 - 2:20 — Live demo, part 2: a new incident comes in
- Run `python -m src.cli_demo new`.
- Narrate while it runs: "This is a *new* incident that looks similar to
  the pool-exhaustion one from earlier. Watch the agent's response --
  it should reference that past incident and its fix, pulled back purely
  via CockroachDB's vector index, not from anything hardcoded in the
  prompt."
- Show the agent's response text on screen, highlighting the reference to
  the earlier incident's root cause.

## 2:20 - 2:45 — Prove the memory persists
- Run `python -m src.cli_demo chat <incident_id>` and ask a follow-up
  question, showing the agent has the full prior conversation even though
  this is a brand-new process invocation.
- One line: "Every one of those steps is a CockroachDB transaction -- kill
  this process mid-incident and the next invocation picks up exactly where
  it left off, because `task_state` is durable."

## 2:45 - 3:00 — Close
- Mention the Lambda deployment (`deploy/deploy.sh`) as the production path.
- Repo URL on screen, thank the judges.

## Recording tips
- Use a terminal with a large font (16pt+) and a light theme for readability
  on video.
- Pre-seed data once before recording so `seed` doesn't need re-running if
  you flub a take -- CockroachDB is durable, your video can be too.
- Keep the CockroachDB Cloud Console SQL shell open in a second tab/window
  to casually prove data landed, but don't spend more than ~15s there.

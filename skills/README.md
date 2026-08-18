# CockroachDB Agent Skills used in this project

This project uses the open-source
[CockroachDB Agent Skills Repo](https://github.com/cockroachdb/agent-skills)
during development, alongside the Managed MCP Server and Distributed Vector
Indexing described in the main [README](../README.md).

## How we used it

While designing `db/schema.sql`, we followed the repo's **schema design**
skill for guidance on:

- Using `gen_random_uuid()` primary keys and secondary indexes that match
  CockroachDB's range-based distribution model (avoiding hot-spotting on a
  monotonically increasing key), which is why `incidents` is indexed on
  `(service_id, status)` rather than relying on a scan of the whole table.
- Correct `VECTOR` column + `CREATE VECTOR INDEX` syntax for the Distributed
  Vector Indexing feature, and choosing cosine distance (`<=>`) as the
  operator for semantic incident recall in `src/memory.py`.
- Client-side retry semantics for `40001` serialization failures, which we
  implemented in `src/db.py::run_in_transaction`.

We also referenced the **operations/observability** skill when writing the
recommended monitoring queries in `docs/architecture.md` (row count and index
usage on `incident_embeddings`, connection pool sizing for Lambda).

## Portable across clients

Because the skills are plain, machine-executable instructions, the same
skill files work whether you're pairing with Claude Code, Cursor, or driving
the agent itself through a LangChain tool -- we treated them purely as
development-time guidance here (no runtime dependency), but a natural
extension of this project would be to expose the same skills to the
*running* agent as an MCP resource, so Sentinel can self-correct its own
schema or query patterns in production. See "Future Work" in the main
README.

## Local copy

If you want to browse the skills used above without leaving this repo:

```bash
git clone https://github.com/cockroachdb/agent-skills /tmp/cockroachdb-agent-skills
ls /tmp/cockroachdb-agent-skills
```

(Not vendored into this repo to avoid duplicating an upstream project --
link to specific skill files here once you've picked exact versions/commits
for your submission writeup.)

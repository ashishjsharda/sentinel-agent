#!/usr/bin/env bash
# Deploys Sentinel Agent to AWS Lambda via SAM, and (optionally) provisions
# the CockroachDB Cloud cluster via the agent-ready ccloud CLI first.
#
# Prereqs:
#   - AWS SAM CLI (`brew install aws-sam-cli` / see AWS docs)
#   - AWS credentials configured (`aws configure`)
#   - ccloud CLI installed and `ccloud auth login` run, if using --provision-db
#   - Bedrock model access enabled for the models in .env (Bedrock console ->
#     Model access)
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ "${1:-}" == "--provision-db" ]]; then
  echo "==> Provisioning CockroachDB Cloud cluster via ccloud CLI"
  ccloud cluster create sentinel-agent \
    --provider aws \
    --region us-east-1 \
    --plan serverless \
    --output json

  echo "==> Fetching connection string"
  ccloud cluster sql-connection-string sentinel-agent \
    --database sentinel \
    --output json
  echo "Copy the connection string above into .env as DATABASE_URL, then re-run this script without --provision-db."
  exit 0
fi

if [[ -z "${DATABASE_URL:-}" ]]; then
  # shellcheck disable=SC1091
  [[ -f .env ]] && source .env
fi

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "DATABASE_URL is not set. Copy .env.example to .env and fill it in, or export it." >&2
  exit 1
fi

echo "==> Applying schema to CockroachDB"
if command -v cockroach >/dev/null; then
  cockroach sql --url "$DATABASE_URL" -f db/schema.sql
else
  echo "cockroach CLI not found locally -- run 'cockroach sql --url \"\$DATABASE_URL\" -f db/schema.sql' from a machine that has it, or paste db/schema.sql into the CockroachDB Cloud SQL shell."
fi

echo "==> Building with SAM"
sam build --template-file deploy/template.yaml

echo "==> Deploying"
sam deploy \
  --template-file .aws-sam/build/template.yaml \
  --stack-name sentinel-agent \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides "DatabaseUrl=${DATABASE_URL}" \
  --resolve-s3

echo "==> Done. Fetch the Function URL with:"
echo "    aws cloudformation describe-stacks --stack-name sentinel-agent --query \"Stacks[0].Outputs\""

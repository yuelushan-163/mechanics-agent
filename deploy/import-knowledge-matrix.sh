#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INPUT_FILE="${1:-${ROOT_DIR}/data/mechanics_knowledge_matrix.jsonl}"

if [[ ! -f "${INPUT_FILE}" ]]; then
  echo "Knowledge JSONL not found: ${INPUT_FILE}" >&2
  exit 1
fi

cd "${ROOT_DIR}"
payload_file="$(mktemp)"
trap 'rm -f "${payload_file}"' EXIT
jq -s '.' "${INPUT_FILE}" >"${payload_file}"

web_password="$(cat deploy/secrets/web_admin_password.initial)"
curl -ksS --fail-with-body \
  --user "admin:${web_password}" \
  -H "Content-Type: application/json" \
  --data-binary "@${payload_file}" \
  https://127.0.0.1/v1/knowledge/documents | jq .

es_container="$(docker compose --env-file .env.server ps -q elasticsearch)"
printf '%s' '{
  "query": {
    "ids": {
      "values": [
        "KNOW-UNIT-001",
        "KNOW-IDEAL-001",
        "KNOW-BC-001",
        "KNOW-STRESS-001"
      ]
    }
  }
}' | docker exec -i "${es_container}" sh -ec '
  password="$(cat /run/secrets/es_password)"
  curl -sS --fail-with-body \
    --user "elastic:${password}" \
    -X POST "http://127.0.0.1:9200/mechanics-agent-knowledge-v1/_delete_by_query?refresh=true&conflicts=proceed" \
    -H "Content-Type: application/json" \
    --data-binary @-
' | jq '{deleted, version_conflicts, failures}'

docker exec "${es_container}" sh -ec '
  password="$(cat /run/secrets/es_password)"
  curl -fsS --user "elastic:${password}" \
    "http://127.0.0.1:9200/mechanics-agent-knowledge-v1/_count"
' | jq .

echo "Knowledge matrix import completed."

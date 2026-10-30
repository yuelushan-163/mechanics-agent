#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

es_container="$(docker compose --env-file .env.server ps -q elasticsearch)"
if [[ -z "${es_container}" ]]; then
  echo "Elasticsearch container is not running." >&2
  exit 1
fi

docker exec "${es_container}" sh -ec '
  password="$(cat /run/secrets/es_password)"
  auth="elastic:${password}"

  curl -fsS --user "${auth}" \
    -X PUT "http://127.0.0.1:9200/_index_template/mechanics-agent-single-node" \
    -H "Content-Type: application/json" \
    --data-binary '\''{
      "index_patterns": ["mechanics-agent-*"],
      "priority": 100,
      "template": {
        "settings": {
          "number_of_shards": 1,
          "number_of_replicas": 0
        }
      }
    }'\''

  curl -fsS --user "${auth}" \
    -X PUT "http://127.0.0.1:9200/mechanics-agent-*/_settings" \
    -H "Content-Type: application/json" \
    --data-binary '\''{"index":{"number_of_replicas":0}}'\''

  curl -fsS --user "${auth}" \
    "http://127.0.0.1:9200/_cluster/health?wait_for_status=green&timeout=30s"
'

echo
echo "Elasticsearch single-node index policy configured."

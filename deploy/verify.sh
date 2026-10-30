#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

docker compose --env-file .env.server ps
curl -fsS http://127.0.0.1/health/live | jq .

mongo_container="$(docker compose --env-file .env.server ps -q mongodb)"
docker exec "${mongo_container}" sh -ec '
  mongosh --quiet --host 127.0.0.1 \
    --username "$MONGO_INITDB_ROOT_USERNAME" \
    --password "$(cat /run/secrets/mongo_root_password)" \
    --authenticationDatabase admin \
    --eval "db.adminCommand(\"ping\")"
'

es_container="$(docker compose --env-file .env.server ps -q elasticsearch)"
docker exec "${es_container}" sh -ec 'curl -fsS \
  --user "elastic:$(cat /run/secrets/es_password)" \
  "http://127.0.0.1:9200/_cluster/health?wait_for_status=green&timeout=5s"
'

if ss -lnt | grep -Eq '(^|[[:space:]])(0\.0\.0\.0|\[::\]):(27017|9200|8000)([[:space:]]|$)'; then
  echo "检测到 MongoDB、Elasticsearch 或 API 调试端口暴露到公网监听地址。" >&2
  exit 1
fi

curl -kfsS https://127.0.0.1/health/live | jq .

echo "验收通过：27017、9200 与 8000 未暴露，HTTPS/API 存活，数据服务正常。"

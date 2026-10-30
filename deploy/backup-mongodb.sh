#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="${ROOT_DIR}/backups/mongodb"
STAMP="$(date +%Y%m%d-%H%M%S)"
mkdir -p "${BACKUP_DIR}"
chmod 0700 "${ROOT_DIR}/backups" "${BACKUP_DIR}"

cd "${ROOT_DIR}"
mongo_container="$(docker compose --env-file .env.server ps -q mongodb)"

docker exec "${mongo_container}" sh -ec '
  mongodump --host 127.0.0.1 \
    --username "$MONGO_INITDB_ROOT_USERNAME" \
    --password "$(cat /run/secrets/mongo_root_password)" \
    --authenticationDatabase admin \
    --archive --gzip
' > "${BACKUP_DIR}/mongo-${STAMP}.archive.gz"

chmod 0600 "${BACKUP_DIR}/mongo-${STAMP}.archive.gz"
find "${BACKUP_DIR}" -type f -name 'mongo-*.archive.gz' -mtime +14 -delete

echo "MongoDB 备份完成: ${BACKUP_DIR}/mongo-${STAMP}.archive.gz"

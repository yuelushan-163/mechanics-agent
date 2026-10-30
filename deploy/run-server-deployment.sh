#!/usr/bin/env bash
set -Eeuo pipefail

cd /opt/mechanics-agent

docker compose --env-file .env.server config --quiet
docker compose --env-file .env.server pull mongodb elasticsearch nginx
./deploy/release.sh 0.1.0

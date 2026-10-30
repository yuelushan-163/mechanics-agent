#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -ne 1 ]]; then
  echo "用法: $0 <版本号，例如 0.1.0>" >&2
  exit 1
fi

VERSION="$1"
if [[ ! "${VERSION}" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][A-Za-z0-9]+)?$ ]]; then
  echo "版本号格式不正确。" >&2
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

if [[ ! -f .env.server ]]; then
  cp .env.server.example .env.server
  chmod 0600 .env.server
fi

if grep -q '^APP_VERSION=' .env.server; then
  sed -i "s/^APP_VERSION=.*/APP_VERSION=${VERSION}/" .env.server
else
  printf '\nAPP_VERSION=%s\n' "${VERSION}" >> .env.server
fi

docker compose --env-file .env.server config --quiet
APP_VERSION="${VERSION}" docker compose --env-file .env.server build api
APP_VERSION="${VERSION}" docker compose --env-file .env.server up -d --remove-orphans
docker compose --env-file .env.server ps

echo "版本 ${VERSION} 已部署。"

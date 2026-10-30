#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -ne 1 ]]; then
  echo "用法: $0 <已存在的版本号>" >&2
  exit 1
fi

VERSION="$1"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

if ! docker image inspect "mechanics-agent:${VERSION}" >/dev/null 2>&1; then
  echo "本机不存在镜像 mechanics-agent:${VERSION}" >&2
  exit 1
fi

sed -i "s/^APP_VERSION=.*/APP_VERSION=${VERSION}/" .env.server
APP_VERSION="${VERSION}" docker compose --env-file .env.server up -d --no-deps api
docker compose --env-file .env.server ps api

echo "API 已回滚到 ${VERSION}。"

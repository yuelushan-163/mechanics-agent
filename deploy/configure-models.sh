#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SECRET_DIR="${ROOT_DIR}/deploy/secrets"
ENV_FILE="${ROOT_DIR}/.env.server"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "请使用 root 账号运行此脚本。" >&2
  exit 1
fi

if [[ ! -t 0 ]]; then
  echo "需要交互式终端才能隐藏输入 API Key；请使用 ssh -t 运行。" >&2
  exit 1
fi

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "服务器配置文件不存在：${ENV_FILE}" >&2
  exit 1
fi

install -d -m 0700 "${SECRET_DIR}"

printf '请输入 SiliconFlow API Key（输入内容不会显示）：'
IFS= read -rs siliconflow_key
printf '\n'

if [[ -z "${siliconflow_key}" ]]; then
  echo "API Key 不能为空。" >&2
  exit 1
fi

cleanup() {
  unset siliconflow_key
}
trap cleanup EXIT

write_api_secret() {
  local secret_name="$1"
  local temporary_file
  temporary_file="$(mktemp "${SECRET_DIR}/.${secret_name}.XXXXXX")"
  printf '%s' "${siliconflow_key}" >"${temporary_file}"
  chown 10001:10001 "${temporary_file}"
  chmod 0400 "${temporary_file}"
  mv -f "${temporary_file}" "${SECRET_DIR}/${secret_name}"
}

set_env_value() {
  local key="$1"
  local value="$2"
  local temporary_file
  temporary_file="$(mktemp "${ROOT_DIR}/.env.server.XXXXXX")"
  awk -v key="${key}" -v value="${value}" '
    BEGIN { replaced = 0 }
    index($0, key "=") == 1 {
      if (!replaced) {
        print key "=" value
        replaced = 1
      }
      next
    }
    { print }
    END {
      if (!replaced) {
        print key "=" value
      }
    }
  ' "${ENV_FILE}" >"${temporary_file}"
  chmod --reference="${ENV_FILE}" "${temporary_file}"
  chown --reference="${ENV_FILE}" "${temporary_file}"
  mv -f "${temporary_file}" "${ENV_FILE}"
}

write_api_secret siliconflow_api_key
write_api_secret embedding_api_key

set_env_value PLANNER_MODE siliconflow
set_env_value EMBEDDING_BASE_URL https://api.siliconflow.cn/v1
set_env_value EMBEDDING_MODEL Qwen/Qwen3-Embedding-0.6B

cd "${ROOT_DIR}"
echo "正在加载规划模型与 Embedding 配置……"
docker compose --env-file .env.server up -d --force-recreate --no-deps api

api_container="$(docker compose --env-file .env.server ps -q api)"
if [[ -z "${api_container}" ]]; then
  echo "API 容器没有启动，请查看 docker compose logs api。" >&2
  exit 1
fi

api_ready=0
for _ in $(seq 1 60); do
  health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "${api_container}" 2>/dev/null || true)"
  if [[ "${health}" == "healthy" ]]; then
    api_ready=1
    break
  fi
  if [[ "${health}" == "unhealthy" || "${health}" == "exited" || "${health}" == "dead" ]]; then
    break
  fi
  sleep 2
done

if [[ "${api_ready}" -ne 1 ]]; then
  echo "API 未能健康启动，最近日志如下：" >&2
  docker compose --env-file .env.server logs --tail 80 api >&2
  exit 1
fi

# API 重建后容器地址可能变化，重建 Nginx 以刷新内部上游地址。
docker compose --env-file .env.server up -d --force-recreate --no-deps nginx

echo "正在分别检测规划模型和 Embedding 模型……"
probe_json="$(docker exec "${api_container}" python -c '
import json
import urllib.request

request = urllib.request.Request(
    "http://127.0.0.1:8000/v1/monitoring/probe",
    data=json.dumps({"targets": ["planner", "embedding"]}).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(request, timeout=180) as response:
    print(response.read().decode("utf-8"))
')"

printf '%s\n' "${probe_json}" | jq '{results: .results}'

planner_status="$(printf '%s' "${probe_json}" | jq -r '.results.planner.status // "error"')"
embedding_status="$(printf '%s' "${probe_json}" | jq -r '.results.embedding.status // "error"')"

if [[ "${planner_status}" != "ok" || "${embedding_status}" != "ok" ]]; then
  echo "至少一个模型连接失败。详细错误已经写入后端日志，并会显示在开发管理页。" >&2
  exit 1
fi

echo "配置成功："
echo "  规划模型：deepseek-ai/DeepSeek-V4-Flash"
echo "  Embedding：Qwen/Qwen3-Embedding-0.6B（1024 维）"
echo "  Token 与费用：已启用自动记录"
echo "下一步可运行 deploy/import-knowledge-matrix.sh，为现有知识生成并写入向量。"

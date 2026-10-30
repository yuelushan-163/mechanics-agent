#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SECRET_DIR="${ROOT_DIR}/deploy/secrets"

install -d -m 0700 "${SECRET_DIR}"
umask 077

if [[ -e "${SECRET_DIR}/mongo_root_password" || -e "${SECRET_DIR}/mongo_app_password" ]]; then
  echo "MongoDB Secret 已存在。为防止凭据与数据库用户失配，本脚本不会覆盖它们。" >&2
  exit 1
fi

mongo_root_password="$(openssl rand -base64 36 | tr -d '\r\n')"
mongo_app_password="$(openssl rand -base64 36 | tr -d '\r\n')"
es_password="$(openssl rand -base64 36 | tr -d '\r\n')"
web_password="$(openssl rand -base64 24 | tr -d '\r\n/+=' | cut -c1-24)"

printf '%s' "${mongo_root_password}" > "${SECRET_DIR}/mongo_root_password"
printf '%s' "${mongo_app_password}" > "${SECRET_DIR}/mongo_app_password"
printf '%s' "${mongo_app_password}" > "${SECRET_DIR}/mongo_api_password"
printf '%s' "${es_password}" > "${SECRET_DIR}/es_password"
printf '%s' "${es_password}" > "${SECRET_DIR}/es_api_password"
printf '%s' "${web_password}" > "${SECRET_DIR}/web_admin_password.initial"
htpasswd -nbB admin "${web_password}" > "${SECRET_DIR}/nginx.htpasswd"

openssl req -x509 -nodes -newkey rsa:3072 -sha256 -days 365 \
  -keyout "${SECRET_DIR}/tls.key" \
  -out "${SECRET_DIR}/tls.crt" \
  -subj "/CN=8.145.63.176" \
  -addext "subjectAltName=IP:8.145.63.176" >/dev/null 2>&1

for secret_name in siliconflow_api_key embedding_api_key moonshot_api_key; do
  if [[ ! -f "${SECRET_DIR}/${secret_name}" ]]; then
    : > "${SECRET_DIR}/${secret_name}"
  fi
done

chown 999:999 \
  "${SECRET_DIR}/mongo_root_password" \
  "${SECRET_DIR}/mongo_app_password"
chown 1000:0 "${SECRET_DIR}/es_password"
chown 10001:10001 \
  "${SECRET_DIR}/mongo_api_password" \
  "${SECRET_DIR}/es_api_password" \
  "${SECRET_DIR}/siliconflow_api_key" \
  "${SECRET_DIR}/embedding_api_key" \
  "${SECRET_DIR}/moonshot_api_key"
chown 101:101 "${SECRET_DIR}/nginx.htpasswd"
chown 0:0 \
  "${SECRET_DIR}/tls.crt" \
  "${SECRET_DIR}/tls.key" \
  "${SECRET_DIR}/web_admin_password.initial"
chmod 0400 \
  "${SECRET_DIR}/mongo_root_password" \
  "${SECRET_DIR}/mongo_app_password" \
  "${SECRET_DIR}/mongo_api_password" \
  "${SECRET_DIR}/es_password" \
  "${SECRET_DIR}/es_api_password" \
  "${SECRET_DIR}/siliconflow_api_key" \
  "${SECRET_DIR}/embedding_api_key" \
  "${SECRET_DIR}/moonshot_api_key" \
  "${SECRET_DIR}/nginx.htpasswd" \
  "${SECRET_DIR}/tls.key"
chmod 0444 "${SECRET_DIR}/tls.crt"
chmod 0600 "${SECRET_DIR}/web_admin_password.initial"
unset mongo_root_password mongo_app_password es_password web_password

echo "Secret 文件已创建，未写入 Git 或镜像。数据库和网页使用独立随机密码。"

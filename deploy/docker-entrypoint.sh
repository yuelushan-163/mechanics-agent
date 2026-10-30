#!/bin/sh
set -eu

load_secret() {
  variable_name="$1"
  secret_path="$2"
  if [ -s "$secret_path" ]; then
    secret_value="$(cat "$secret_path")"
    export "$variable_name=$secret_value"
  fi
}

load_secret SILICONFLOW_API_KEY /run/secrets/siliconflow_api_key
load_secret EMBEDDING_API_KEY /run/secrets/embedding_api_key
load_secret MOONSHOT_API_KEY /run/secrets/moonshot_api_key
load_secret ES_PASSWORD /run/secrets/es_password
load_secret MONGO_APP_PASSWORD /run/secrets/mongo_app_password

exec "$@"

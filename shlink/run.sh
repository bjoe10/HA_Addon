#!/usr/bin/with-contenv bash
set -e

CONFIG_PATH=/data/shlink
mkdir -p "$CONFIG_PATH"

DEFAULT_DOMAIN=$(jq -r '.default_domain' /data/options.json)
IS_HTTPS_ENABLED=$(jq -r '.is_https_enabled' /data/options.json)
TZ=$(jq -r '.timezone' /data/options.json)

export SHLINK_DEFAULT_DOMAIN="$DEFAULT_DOMAIN"
export SHLINK_IS_HTTPS_ENABLED="$IS_HTTPS_ENABLED"
export SHLINK_DB_DRIVER=sqlite
export SHLINK_DB_NAME="$CONFIG_PATH/database.sqlite"
export SHLINK_TIMEZONE="$TZ"

echo "Starting Shlink for domain: $DEFAULT_DOMAIN"

exec /usr/bin/entrypoint.sh shlink serve -vvv

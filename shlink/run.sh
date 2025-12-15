#!/usr/bin/with-contenv bash
set -e

OPTIONS=/data/options.json
DATA_DIR=/data/shlink
mkdir -p "$DATA_DIR"

export SHLINK_DEFAULT_DOMAIN=$(jq -r '.default_domain' "$OPTIONS")
export SHLINK_IS_HTTPS_ENABLED=$(jq -r '.is_https_enabled' "$OPTIONS")
export SHLINK_TIMEZONE=$(jq -r '.timezone' "$OPTIONS")
export SHLINK_ANONYMIZE_REMOTE_ADDR=$(jq -r '.anonymize_remote_addr' "$OPTIONS")

DB_DRIVER=$(jq -r '.db_driver' "$OPTIONS")

if [ "$DB_DRIVER" = "sqlite" ]; then
  export SHLINK_DB_DRIVER=sqlite
  export SHLINK_DB_NAME="$DATA_DIR/database.sqlite"
else
  export SHLINK_DB_DRIVER=maria
  export SHLINK_DB_HOST=$(jq -r '.db_host' "$OPTIONS")
  export SHLINK_DB_PORT=$(jq -r '.db_port' "$OPTIONS")
  export SHLINK_DB_NAME=$(jq -r '.db_name' "$OPTIONS")
  export SHLINK_DB_USER=$(jq -r '.db_user' "$OPTIONS")
  export SHLINK_DB_PASSWORD=$(jq -r '.db_password' "$OPTIONS")
fi

GEO_KEY=$(jq -r '.geolite_license_key' "$OPTIONS")
if [ "$GEO_KEY" != "" ] && [ "$GEO_KEY" != "null" ]; then
  export SHLINK_GEOLITE_LICENSE_KEY="$GEO_KEY"
fi

echo "Starting Shlink for ${SHLINK_DEFAULT_DOMAIN}"
exec /usr/bin/entrypoint.sh shlink serve -vvv

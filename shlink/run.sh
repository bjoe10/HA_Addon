#!/usr/bin/with-contenv bash
set -e

CONFIG_PATH=/data/options.json

export DEFAULT_DOMAIN=$(jq -r '.DEFAULT_DOMAIN' $CONFIG_PATH)
export IS_HTTPS_ENABLED=$(jq -r '.IS_HTTPS_ENABLED' $CONFIG_PATH)
export INITIAL_API_KEY=$(jq -r '.INITIAL_API_KEY' $CONFIG_PATH)
export DB_DRIVER=$(jq -r '.DB_DRIVER' $CONFIG_PATH)
export DB_NAME=$(jq -r '.DB_NAME' $CONFIG_PATH)

exec shlink


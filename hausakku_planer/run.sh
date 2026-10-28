#!/usr/bin/with-contenv bashio
export HAUSAKKU_DATA=/data
export HAUSAKKU_LOG_LEVEL="$(bashio::config 'log_level')"
cd /app
exec python3 -m service

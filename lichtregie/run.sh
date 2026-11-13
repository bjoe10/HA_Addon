#!/usr/bin/with-contenv bashio
# HA-Zugang über den Supervisor (SUPERVISOR_TOKEN kommt aus der Umgebung), Daten unter /data,
# Art-Net-Nodes aus der gemappten HA-Konfiguration (/homeassistant/configuration.yaml).
export LICHTREGIE_DATA=/data
export LICHTREGIE_PORT=8099
export LICHTREGIE_HA_API=http://supervisor/core/api
export LICHTREGIE_HA_CONFIG=/homeassistant:/config
export LICHTREGIE_PLAYER="$(bashio::config 'spotify_player')"
export LICHTREGIE_FREQBLOG_KEY="$(bashio::config 'freqblog_key')"
cd /app
exec python3 -u server.py

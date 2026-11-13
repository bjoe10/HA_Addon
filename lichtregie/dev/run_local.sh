#!/bin/sh
# Lichtregie lokal auf dem Mac starten, mit demselben Code wie im Add-on (app/).
# HA-Zugang über einen eigenen Token, Daten im Ordner dev/.data (nicht im Repo).
# Aufruf: dev/run_local.sh   → Oberfläche unter http://<IP des Mac>:8765
DIR="$(cd "$(dirname "$0")" && pwd)"
export LICHTREGIE_DATA="$DIR/.data"
export LICHTREGIE_PORT=8765
export LICHTREGIE_HA_API="http://192.168.178.108:8123/api"
export LICHTREGIE_HA_TOKEN_FILE="$HOME/.config/lichtregie/ha.token"
export LICHTREGIE_FREQBLOG_KEY_FILE="$HOME/.config/lichtregie/freqblog.key"
# Spotify-Player-Entität aus einer lokalen Datei (nicht im Repo), z. B. media_player.spotify_name
export LICHTREGIE_PLAYER="${LICHTREGIE_PLAYER:-$(cat "$HOME/.config/lichtregie/player" 2>/dev/null)}"
export LICHTREGIE_HA_CONFIG="$DIR/.data"   # lokal keine HA-configuration.yaml: Standardwerte der Nodes
mkdir -p "$LICHTREGIE_DATA"
cd "$DIR/../app" && exec python3 -u server.py

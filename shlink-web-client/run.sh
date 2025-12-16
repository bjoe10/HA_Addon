
#!/usr/bin/env bash
# shellcheck shell=bash
set -euo pipefail

CONFIG_PATH="/data/options.json"
DOC_ROOT="/usr/share/nginx/html"
SERVERS_JSON="${DOC_ROOT}/servers.json"

# Optionen aus /data/options.json lesen (werden vom Supervisor geschrieben)
read_option() {
  jq -r "$1 // empty" "${CONFIG_PATH}"
}

SHLINK_URL="$(read_option '.shlink_server_url')"
SHLINK_API_KEY="$(read_option '.shlink_server_api_key')"
SHLINK_NAME="$(read_option '.shlink_server_name')"
FORWARD_CRED="$(read_option '.forward_credentials')"

# Fallbacks
SHLINK_NAME="${SHLINK_NAME:-Shlink}"
FORWARD_CRED="${FORWARD_CRED:-false}"

# servers.json zusammenstellen
# Struktur gemäß Shlink-Web-Client-Doku, optional mit forwardCredentials
# Achtung: Die Datei wird nur beim ersten Laden auf einem Gerät eingelesen
# (danach speichert der Browser die Server in LocalStorage). [2](https://shlink.io/documentation/shlink-web-client/pre-configuring-servers/)
mkdir -p "${DOC_ROOT}"

# Beginne mit leerer Liste
tmpfile="$(mktemp)"
echo "[]" > "${tmpfile}"

# Default-Server aus GUI-Optionen hinzufügen (falls gesetzt)
if [[ -n "${SHLINK_URL}" && -n "${SHLINK_API_KEY}" ]]; then
  jq --arg name "${SHLINK_NAME}" \
     --arg url "${SHLINK_URL}" \
     --arg api "${SHLINK_API_KEY}" \
     --argjson fwd "$( [[ "${FORWARD_CRED}" == "true" ]] && echo true || echo false )" \
     '. + [ {name: $name, url: $url, apiKey: $api, forwardCredentials: $fwd} ]' \
     "${tmpfile}" > "${SERVERS_JSON}"
else
  # keine Vorkonfiguration -> leere Liste schreiben
  mv "${tmpfile}" "${SERVERS_JSON}"
fi

echo "[INFO] servers.json geschrieben nach ${SERVERS_JSON}"
echo "[INFO] Starte nginx …"

# nginx im Vordergrund starten (Image liefert die Konfiguration out of the box). [1](https://hub.docker.com/r/shlinkio/shlink-web-client/)
exec nginx -g 'daemon off;'
``



#!/usr/bin/env bash
set -euo pipefail

OPTIONS_FILE=/data/options.json
HTML_ROOT=/usr/share/nginx/html
ADDON_CONFIG_DIR=/config  # via "map: addon_config" eingebunden

# 1) Optional: Benutzer-servers.json aus addon_config übernehmen
if [ -f "${ADDON_CONFIG_DIR}/servers.json" ]; then
  cp -f "${ADDON_CONFIG_DIR}/servers.json" "${HTML_ROOT}/servers.json"
  echo "[INFO] Using user-provided servers.json from ${ADDON_CONFIG_DIR}"
else
  # 2) servers.json aus Add-on-Optionen erzeugen (wenn URL & API-Key gesetzt)
  if [ -f "${OPTIONS_FILE}" ]; then
    URL=$(jq -r '.shlink_server_url // empty' "$OPTIONS_FILE")
    API_KEY=$(jq -r '.shlink_server_api_key // empty' "$OPTIONS_FILE")
    NAME=$(jq -r '.shlink_server_name // "Shlink"' "$OPTIONS_FILE")
    FWD=$(jq -r '.forward_credentials // false' "$OPTIONS_FILE")

    if [ -n "${URL}" ] && [ -n "${API_KEY}" ]; then
      cat > "${HTML_ROOT}/servers.json" <<EOF
[
  {
    "name": ${NAME@Q},
    "url": ${URL@Q},
    "apiKey": ${API_KEY@Q},
    "forwardCredentials": ${FWD}
  }
]
EOF
      echo "[INFO] Generated ${HTML_ROOT}/servers.json from Add-on options."
    else
      echo "[INFO] No URL/API key provided in options; starting without preconfigured server."
    fi
  fi
fi

# 3) nginx starten (Image basiert auf nginx:alpine)
exec nginx -g "daemon off;"

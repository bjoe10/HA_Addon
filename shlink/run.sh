
#!/usr/bin/env bash
set -euo pipefail

log() { echo "[shlink-addon] $*"; }

OPTIONS_FILE="/data/options.json"
# JSON-Optionen aus der HA-UI lesen (jq bevorzugt; Fallback ohne jq)
get_opt(){
  local key="$1"; local default="${2-}"
  if command -v jq >/dev/null 2>&1; then
    local val
    val=$(jq -r --arg k "$key" '.[$k] // empty' "$OPTIONS_FILE" 2>/dev/null || true)
    if [ -z "${val}" ] || [ "${val}" = "null" ]; then echo -n "$default"; else echo -n "$val"; fi
  else
    local val
    val=$(sed -n "s/.*\"$key\" *: *\"\(.*\)\".*/\1/p" "$OPTIONS_FILE" | head -n1)
    if [ -z "${val}" ]; then echo -n "$default"; else echo -n "$val"; fi
  fi
}

# --- Persistenz für Shlink-Dateien (SQLite etc.) ---
PERSIST_DIR="/data/etc-shlink"
if [ ! -d "$PERSIST_DIR" ]; then
  mkdir -p "$PERSIST_DIR"
fi
# /etc/shlink -> /data/etc-shlink symlink
if [ -d "/etc/shlink" ] && [ ! -L "/etc/shlink" ]; then
  if [ -z "$(ls -A /etc/shlink)" ]; then
    rmdir /etc/shlink || true
  else
    log "Migrating /etc/shlink to $PERSIST_DIR for persistence..."
    cp -a /etc/shlink/. "$PERSIST_DIR"/
    rm -rf /etc/shlink
  fi
fi
if [ ! -e "/etc/shlink" ]; then
  ln -s "$PERSIST_DIR" /etc/shlink
fi

# --- Optionen aus der HA-UI ---
DEFAULT_DOMAIN=$(get_opt default_domain "")
IS_HTTPS_ENABLED=$(get_opt is_https_enabled "true")
GEOLITE_LICENSE_KEY=$(get_opt geolite_license_key "")
BASE_PATH=$(get_opt base_path "")
TIMEZONE=$(get_opt timezone "UTC")
TRUSTED_PROXIES=$(get_opt trusted_proxies "")
LOGS_FORMAT=$(get_opt logs_format "console")
MEMORY_LIMIT=$(get_opt memory_limit "512M")
PROVIDED_API_KEY=$(get_opt initial_api_key "")

# --- Shlink-ENV Variablen ---
export DEFAULT_DOMAIN="$DEFAULT_DOMAIN"
export IS_HTTPS_ENABLED="$IS_HTTPS_ENABLED"
[ -n "$GEOLITE_LICENSE_KEY" ] && export GEOLITE_LICENSE_KEY
[ -n "$BASE_PATH" ] && export BASE_PATH
[ -n "$TIMEZONE" ] && export TIMEZONE
[ -n "$TRUSTED_PROXIES" ] && export TRUSTED_PROXIES
[ -n "$LOGS_FORMAT" ] && export LOGS_FORMAT
[ -n "$MEMORY_LIMIT" ] && export MEMORY_LIMIT

# --- Keine externe DB: wir bleiben bei SQLite (Shlink nutzt sie automatisch) ---

# --- API-Key handhaben ---
API_KEY_FILE="/data/api_key.txt"
API_KEY=""
if [ -s "$API_KEY_FILE" ]; then
  API_KEY=$(cat "$API_KEY_FILE")
  log "Existing API key found in $API_KEY_FILE."
else
  if [ -n "$PROVIDED_API_KEY" ]; then
    API_KEY="$PROVIDED_API_KEY"
  else
    if command -v uuidgen >/dev/null 2>&1; then
      API_KEY=$(uuidgen | tr 'A-Z' 'a-z')
    elif [ -r /proc/sys/kernel/random/uuid ]; then
      API_KEY=$(cat /proc/sys/kernel/random/uuid)
    else
      API_KEY=$(date +%s%N | sha256sum | cut -c1-32)
    fi
  fi
  echo -n "$API_KEY" > "$API_KEY_FILE"
  chmod 600 "$API_KEY_FILE"
fi

# Shlink >= 3.3: ersten API-Key via INITIAL_API_KEY setzen
export INITIAL_API_KEY="$API_KEY"

# Deutlich im Add-on-Log ausgeben
log "
================ SHLINK API KEY ================
$API_KEY
================================================
"

# --- Shlink starten: an originalen Entrypoint delegieren ---
if command -v docker-entrypoint.sh >/dev/null 2>&1; then
  exec docker-entrypoint.sh
elif [ -x /usr/local/bin/docker-entrypoint.sh ]; then
  exec /usr/local/bin/docker-entrypoint.sh
elif [ -x /entrypoint.sh ]; then
  exec /entrypoint.sh
else
  # Fallback RoadRunner/CLI
  if command -v rr >/dev/null 2>&1; then
    exec rr serve
  fi
  if command -v shlink >/dev/null 2>&1; then
    exec shlink serve || shlink -V || sleep infinity
  fi
  log "Could not determine how to start Shlink. Going idle."
  exec tail -f /dev/null
fi



#!/usr/bin/env bash
set -euo pipefail

log() { echo "[shlink-addon] $*"; }

OPTIONS_FILE="/data/options.json"
# Simple JSON reader using jq (fallback ohne jq)
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

# --- Persistenz für Shlink-Dateien ---
PERSIST_DIR="/data/etc-shlink"
if [ ! -d "$PERSIST_DIR" ]; then
  mkdir -p "$PERSIST_DIR"
fi
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

# --- Optionen lesen ---
DEFAULT_DOMAIN=$(get_opt default_domain "")
IS_HTTPS_ENABLED=$(get_opt is_https_enabled "true")
GEOLITE_LICENSE_KEY=$(get_opt geolite_license_key "")
BASE_PATH=$(get_opt base_path "")
TIMEZONE=$(get_opt timezone "UTC")
TRUSTED_PROXIES=$(get_opt trusted_proxies "")
LOGS_FORMAT=$(get_opt logs_format "console")
MEMORY_LIMIT=$(get_opt memory_limit "512M")

DB_DRIVER=$(get_opt db_driver "sqlite")
DB_HOST=$(get_opt db_host "")
DB_PORT=$(get_opt db_port "")
DB_NAME=$(get_opt db_name "shlink")
DB_USER=$(get_opt db_user "")
DB_PASSWORD=$(get_opt db_password "")

PROVIDED_API_KEY=$(get_opt initial_api_key "")
API_KEY_FILE="/data/api_key.txt"

# --- Shlink-ENV Variablen exportieren ---
export DEFAULT_DOMAIN="$DEFAULT_DOMAIN"
export IS_HTTPS_ENABLED="$IS_HTTPS_ENABLED"
[ -n "$GEOLITE_LICENSE_KEY" ] && export GEOLITE_LICENSE_KEY
[ -n "$BASE_PATH" ] && export BASE_PATH
[ -n "$TIMEZONE" ] && export TIMEZONE
[ -n "$TRUSTED_PROXIES" ] && export TRUSTED_PROXIES
[ -n "$LOGS_FORMAT" ] && export LOGS_FORMAT
[ -n "$MEMORY_LIMIT" ] && export MEMORY_LIMIT

case "$DB_DRIVER" in
  sqlite|"")
    # SQLite (im /etc/shlink via Symlink) – keine weiteren ENV nötig
    ;;
  mysql|maria|postgres|mssql)
    export DB_DRIVER
    [ -n "$DB_NAME" ] && export DB_NAME
    [ -n "$DB_USER" ] && export DB_USER
    [ -n "$DB_PASSWORD" ] && export DB_PASSWORD
    [ -n "$DB_HOST" ] && export DB_HOST
    [ -n "$DB_PORT" ] && export DB_PORT
    ;;
  *)
    log "Unsupported DB driver: $DB_DRIVER. Falling back to SQLite."
    ;;
esac

# --- API-Key: aus Optionen, Datei oder neu generieren ---
FIRST_RUN=false
API_KEY=""
if [ -s "$API_KEY_FILE" ]; then
  API_KEY=$(cat "$API_KEY_FILE")
  log "Existing API key found in $API_KEY_FILE."
else
  if [ -n "$PROVIDED_API_KEY" ]; then
    API_KEY="$PROVIDED_API_KEY"
    echo -n "$API_KEY" > "$API_KEY_FILE"
    chmod 600 "$API_KEY_FILE"
    log "Using user-provided initial API key from options. Saved to $API_KEY_FILE."
  else
    if command -v uuidgen >/dev/null 2>&1; then
      API_KEY=$(uuidgen | tr 'A-Z' 'a-z')
    elif [ -r /proc/sys/kernel/random/uuid ]; then
      API_KEY=$(cat /proc/sys/kernel/random/uuid)
    else
      API_KEY=$(date +%s%N | sha256sum | cut -c1-32)
    fi
    echo -n "$API_KEY" > "$API_KEY_FILE"
    chmod 600 "$API_KEY_FILE"
    FIRST_RUN=true
    log "Generated new initial API key. Saved to $API_KEY_FILE."
  fi
fi

# Shlink ab v3.3 akzeptiert INITIAL_API_KEY als Startwert
export INITIAL_API_KEY="$API_KEY"

# Deutlich im Log ausgeben
log "
================ SHLINK API KEY ================
$API_KEY
================================================
"

# --- Shlink starten (an den ursprünglichen Entrypoint delegieren) ---
if command -v docker-entrypoint.sh >/dev/null 2>&1; then
  exec docker-entrypoint.sh
elif [ -x /usr/local/bin/docker-entrypoint.sh ]; then
  exec /usr/local/bin/docker-entrypoint.sh
elif [ -x /entrypoint.sh ]; then
  exec /entrypoint.sh
else
  if command -v rr >/dev/null 2>&1; then
    exec rr serve
  fi
  if command -v shlink >/dev/null 2>&1; then
    exec shlink serve || shlink -V || sleep infinity
  fi
  log "Could not determine how to start Shlink. Going idle."
  exec tail -f /dev/null
fi

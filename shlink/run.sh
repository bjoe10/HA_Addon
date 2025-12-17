
#!/bin/sh
set -eu

# 0) Optionen aus HA-GUI
export CONFIG_PATH="/data/options.json"
get_opt() {
  key="$1"; default="${2:-}"
  val="$(php -r '
    $p=getenv("CONFIG_PATH");
    $j=@json_decode(@file_get_contents($p),true);
    $k=$argv[1];
    if(is_array($j)&&array_key_exists($k,$j)&&$j[$k]!==null){echo $j[$k];}
  ' "$key" 2>/dev/null || true)"
  if [ -n "${val:-}" ]; then printf "%s" "$val"; else printf "%s" "$default"; fi
}

# 1) ENV für Shlink
export DEFAULT_DOMAIN="$(get_opt default_domain s.test)"
export IS_HTTPS_ENABLED="$(get_opt is_https_enabled false)"
export GEOLITE_LICENSE_KEY="$(get_opt geolite_license_key "")"
export BASE_PATH="$(get_opt base_path "")"
export TIMEZONE="$(get_opt timezone UTC)"
export TRUSTED_PROXIES="$(get_opt trusted_proxies "")"
export LOGS_FORMAT="$(get_opt logs_format console)"

# 2) Initialen API-Key nur beim Erststart
INITIAL_API_KEY_CFG="$(get_opt initial_api_key "")"
if [ -n "$INITIAL_API_KEY_CFG" ]; then
  export INITIAL_API_KEY="$INITIAL_API_KEY_CFG"
else
  export INITIAL_API_KEY="$(php -r 'echo bin2hex(random_bytes(16));')"
fi
echo "Shlink Add-on: INITIAL_API_KEY = ${INITIAL_API_KEY}"

# 3) SQLite unter /data persistieren
PERSIST_DIR="/data/shlink"
CONTAINER_DB_DIR="/etc/shlink/data"
SHLINK_UID="${SHLINK_UID:-1001}"
SHLINK_GID="${SHLINK_GID:-1001}"

mkdir -p "${PERSIST_DIR}"
if [ -d "${CONTAINER_DB_DIR}" ] && [ ! -L "${CONTAINER_DB_DIR}" ]; then
  if [ -z "$(ls -A "${PERSIST_DIR}" 2>/dev/null || true)" ]; then
    cp -a "${CONTAINER_DB_DIR}/." "${PERSIST_DIR}/" || true
  fi
  rm -rf "${CONTAINER_DB_DIR}"
fi
if [ ! -L "${CONTAINER_DB_DIR}" ]; then
  ln -s "${PERSIST_DIR}" "${CONTAINER_DB_DIR}"
fi
chown -R "${SHLINK_UID}:${SHLINK_GID}" "${PERSIST_DIR}" || true
chmod 0775 "${PERSIST_DIR}" || true
echo "Shlink Add-on: SQLite persistiert unter ${PERSIST_DIR}"

# 4) Originalen Shlink-Entrypoint starten
if [ -x "/docker-entrypoint.sh" ]; then
  exec /docker-entrypoint.sh
fi

echo "Fehler: /docker-entrypoint.sh fehlt – falsches Image?"
exit


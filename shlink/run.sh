
#!/bin/sh
set -eu

# -------------------------------------------------------------------
# 0) HA-Optionen lesen
# -------------------------------------------------------------------
export CONFIG_PATH="/data/options.json"

get_opt() {
  key="$1"; default="${2:-}"
  # Kleiner, robuster PHP-One-Liner statt jq/bashio
  val="$(php -r '
    $p=getenv("CONFIG_PATH");
    $j=@json_decode(@file_get_contents($p),true);
    $k=$argv[1];
    if(is_array($j)&&array_key_exists($k,$j)&&$j[$k]!==null){echo $j[$k];}
  ' "$key" 2>/dev/null || true)"
  if [ -n "${val:-}" ]; then printf "%s" "$val"; else printf "%s" "$default"; fi
}

# -------------------------------------------------------------------
# 1) Shlink-ENV aus GUI-Optionen ableiten
# -------------------------------------------------------------------
export DEFAULT_DOMAIN="$(get_opt default_domain s.test)"
export IS_HTTPS_ENABLED="$(get_opt is_https_enabled false)"
export GEOLITE_LICENSE_KEY="$(get_opt geolite_license_key "")"
export BASE_PATH="$(get_opt base_path "")"
export TIMEZONE="$(get_opt timezone UTC)"
export TRUSTED_PROXIES="$(get_opt trusted_proxies "")"
export LOGS_FORMAT="$(get_opt logs_format console)"

# -------------------------------------------------------------------
# 2) Initialen API-Key setzen/erzeugen (Shlink nutzt ihn nur beim Erststart)
# -------------------------------------------------------------------
INITIAL_API_KEY_CFG="$(get_opt initial_api_key "")"
if [ -n "$INITIAL_API_KEY_CFG" ]; then
  export INITIAL_API_KEY="$INITIAL_API_KEY_CFG"
else
  export INITIAL_API_KEY="$(php -r 'echo bin2hex(random_bytes(16));')"
fi
echo "Shlink Add-on: INITIAL_API_KEY = ${INITIAL_API_KEY}"
echo "Hinweis: INITIAL_API_KEY wird von Shlink nur beim allerersten Start verwendet."

# -------------------------------------------------------------------
# 3) SQLite-Persistenz: /etc/shlink/data -> /data/shlink (Symlink)
# -------------------------------------------------------------------
PERSIST_DIR="/data/shlink"
CONTAINER_DB_DIR="/etc/shlink/data"

# Standard-UID/GID des Shlink-Laufzeit-Users im offiziellen Image
SHLINK_UID="${SHLINK_UID:-1001}"
SHLINK_GID="${SHLINK_GID:-1001}"

# Persistenzverzeichnis anlegen
mkdir -p "${PERSIST_DIR}"

# Falls Containerverzeichnis noch echte Dateien enthält (Erststart), herüberkopieren
if [ -d "${CONTAINER_DB_DIR}" ] && [ ! -L "${CONTAINER_DB_DIR}" ]; then
  if [ -z "$(ls -A "${PERSIST_DIR}" 2>/dev/null || true)" ]; then
    cp -a "${CONTAINER_DB_DIR}/." "${PERSIST_DIR}/" || true
  fi
  rm -rf "${CONTAINER_DB_DIR}"
fi

# Symlink setzen, falls noch nicht vorhanden
if [ ! -L "${CONTAINER_DB_DIR}" ]; then
  ln -s "${PERSIST_DIR}" "${CONTAINER_DB_DIR}"
fi

# Rechte so setzen, dass Shlink schreiben kann
chown -R "${SHLINK_UID}:${SHLINK_GID}" "${PERSIST_DIR}" || true
chmod 0775 "${PERSIST_DIR}" || true

echo "Shlink Add-on: SQLite persistiert unter ${PERSIST_DIR}"

# -------------------------------------------------------------------
# 4) Shlink starten (Original-Entrypoint des Upstream-Images)
# -------------------------------------------------------------------
if [ -x "/docker-entrypoint.sh" ]; then
  exec /docker-entrypoint.sh
fi

# Fallback, falls sich die Image-Struktur ändert
echo "WARN: /docker-entrypoint.sh nicht gefunden – bitte Image/Tag prüfenecho "WARN: /docker-entrypoint.sh nicht gefunden – bitte Image/Tag prüfen."


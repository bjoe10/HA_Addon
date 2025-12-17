
#!/bin/sh
set -eu

export CONFIG_PATH="/data/options.json"

# JSON-Wert via PHP aus /data/options.json lesen (ohne jq/bashio)
get_opt() {
  key="$1"; default="${2:-}"
  val="$(php -r '
    $p = getenv("CONFIG_PATH");
    $j = @json_decode(@file_get_contents($p), true);
    $k = $argv[1];
    if (is_array($j) && array_key_exists($k, $j) && $j[$k] !== null) { echo $j[$k]; }
  ' "$key" 2>/dev/null || true)"
  if [ -n "${val:-}" ]; then printf "%s" "$val"; else printf "%s" "$default"; fi
}

# 1) Optionen aus HA-GUI -> ENV für Shlink
export DEFAULT_DOMAIN="$(get_opt default_domain s.test)"
export IS_HTTPS_ENABLED="$(get_opt is_https_enabled false)"
export GEOLITE_LICENSE_KEY="$(get_opt geolite_license_key "")"
export BASE_PATH="$(get_opt base_path "")"
export TIMEZONE="$(get_opt timezone UTC)"
export TRUSTED_PROXIES="$(get_opt trusted_proxies "")"
export LOGS_FORMAT="$(get_opt logs_format console)"

# 2) Initialen API-Key setzen/erzeugen (einmalig beim Erststart)
INITIAL_API_KEY_CFG="$(get_opt initial_api_key "")"
if [ -n "$INITIAL_API_KEY_CFG" ]; then
  export INITIAL_API_KEY="$INITIAL_API_KEY_CFG"
else
  # kryptographisch zufälliger Key (32 hex)
  export INITIAL_API_KEY="$(php -r 'echo bin2hex(random_bytes(16));')"
fi

echo "Shlink Add-on: INITIAL_API_KEY = ${INITIAL_API_KEY}"
echo "Hinweis: INITIAL_API_KEY wird von Shlink nur beim allerersten Start verwendet, wenn noch keine API-Keys existieren."

# 3) SQLite-Persistenz unter /data einrichten (mit Fallback)
PERSIST_DIR="/data/shlink"
CONTAINER_DB_DIR="/etc/shlink/data"

# UID des späteren Shlink-Laufzeit-Users (typisch 1001 im offiziellen Image)
SHLINK_UID="${SHLINK_UID:-1001}"
SHLINK_GID="${SHLINK_GID:-1001}"

if mkdir -p "${PERSIST_DIR}" 2>/dev/null; then
  # Rechte/Owner so setzen, dass der Nicht-Root-Laufzeit-User schreiben kann
  chmod 0775 "${PERSIST_DIR}" || true
  chown -R "${SHLINK_UID}:${SHLINK_GID}" "${PERSIST_DIR}" || true

  # Containerpfad auf Persistenz umbiegen, falls noch kein Symlink
  if [ -d "${CONTAINER_DB_DIR}" ] && [ ! -L "${CONTAINER_DB_DIR}" ]; then
    cp -rT "${CONTAINER_DB_DIR}" "${PERSIST_DIR}" || true
    rm -rf "${CONTAINER_DB_DIR}"
    ln -s "${PERSIST_DIR}" "${CONTAINER_DB_DIR}"
  fi

  echo "Shlink Add-on: SQLite persistiert unter ${PERSIST_DIR}"
else
  echo "Shlink Add-on: WARNUNG: Keine Schreibrechte auf /data – SQLite bleibt intern (nicht persistent)."
fi

# 4) Originalen Shlink-Entrypoint ausführen
if [ -x "/docker-entrypoint.sh" ]; then
  exec /docker-entrypoint.sh
else
  echo "Fehler: /docker-entrypoint.sh nicht gefunden! Bitte Image-Tag prüfen."
  exit 1
fi
``


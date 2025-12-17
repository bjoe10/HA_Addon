
#!/usr/bin/env bash
set -euo pipefail

CONFIG_PATH="/data/options.json"

# Fallback-Funktionen zum Lesen aus options.json, ohne bashio
get_opt() {
  local key="$1"; local default="${2:-}"
  if command -v jq >/dev/null 2>&1 && [ -f "$CONFIG_PATH" ]; then
    jq -r --arg k "$key" '.[$k] // empty' "$CONFIG_PATH" 2>/dev/null || echo -n "$default"
  else
    echo -n "$default"
  fi
}

# 1) Optionen aus HA GUI laden und als ENV für Shlink setzen
export DEFAULT_DOMAIN="$(get_opt default_domain s.test)"
export IS_HTTPS_ENABLED="$(get_opt is_https_enabled false)"
export GEOLITE_LICENSE_KEY="$(get_opt geolite_license_key "")"
export BASE_PATH="$(get_opt base_path "")"
export TIMEZONE="$(get_opt timezone UTC)"
export TRUSTED_PROXIES="$(get_opt trusted_proxies "")"
export LOGS_FORMAT="$(get_opt logs_format console)"

# 2) Optional: Initialen API-Key setzen oder generieren
INITIAL_API_KEY_CFG="$(get_opt initial_api_key "")"
if [ -n "$INITIAL_API_KEY_CFG" ]; then
  export INITIAL_API_KEY="$INITIAL_API_KEY_CFG"
else
  # Einmaligen, zufälligen Initial-Key generieren (UUID v4)
  if command -v uuidgen >/dev/null 2>&1; then
    export INITIAL_API_KEY="$(uuidgen)"
  else
    # einfacher Fallback, 32 Hexzeichen
    export INITIAL_API_KEY="$(cat /proc/sys/kernel/random/uuid 2>/dev/null || echo $(date +%s%N))"
  fi
fi

echo "Shlink Add-on: INITIAL_API_KEY = ${INITIAL_API_KEY}"
echo "Hinweis: INITIAL_API_KEY wird von Shlink nur beim allerersten Start verwendet, wenn noch keine API-Keys existieren."  # Doku-Hinweis

# 3) SQLite persistent machen:
#    Shlink hält die SQLite-Datei standardmäßig unter data/database.sqlite
#    (im Image z. B. /etc/shlink/data/database.sqlite). Wir verlinken sie in /data/shlink/.
PERSIST_DIR="/data/shlink"
CONTAINER_DB_DIR="/etc/shlink/data"
CONTAINER_DB_FILE="${CONTAINER_DB_DIR}/database.sqlite"
mkdir -p "${PERSIST_DIR}"

# Wenn im Container noch keine DB existiert, wird Shlink sie beim Start anlegen.
# Wir sorgen dafür, dass das Verzeichnis nach /data zeigt.
if [ -d "${CONTAINER_DB_DIR}" ] && [ ! -L "${CONTAINER_DB_DIR}" ]; then
  # Inhalte (falls vorhanden) nach /data/shlink kopieren
  cp -rT "${CONTAINER_DB_DIR}" "${PERSIST_DIR}" || true

  # Verzeichnis im Container auf persistenten Pfad umbiegen
  rm -rf "${CONTAINER_DB_DIR}"
  ln -s "${PERSIST_DIR}" "${CONTAINER_DB_DIR}"
fi

echo "Shlink Add-on: SQLite persistiert unter ${PERSIST_DIR} (Achtung: SQLite hat bekannte Limitierungen)."

# 4) Zum Schluss das originale Shlink Entrypoint starten
#    Der Entrypoint im offiziellen Image heißt /docker-entrypoint.sh
if [ -x "/docker-entrypoint.sh" ]; then
  exec /docker-entrypoint.sh
else
  echo "Fehler: /docker-entrypoint.sh nicht gefunden!"
  echo "Bitte ggf. Bild-Tag prüfen oder Entrypoint-Pfad anpassen."
  exit 1
fi


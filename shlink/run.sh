
#!/bin/sh
set -eu

CONFIG_PATH="/data/options.json"
API_KEY_FILE="/data/api_key.txt"

echo "[INFO] Shlink Add-on startet. Lese Optionen aus ${CONFIG_PATH}"

# --- JSON lesen mit PHP (keine Zusatztools nötig) ---
json_get() {
  KEY="$1"
  php -r '($o=json_decode(file_get_contents("'"$CONFIG_PATH"'"), true)) && isset($o["'"$KEY"'"]) ? print($o["'"$KEY"'"]) : "";' 2>/dev/null || true
}

# --- Optionen ---
DEFAULT_DOMAIN="$(json_get default_domain)"
IS_HTTPS_ENABLED="$(json_get is_https_enabled)"
GEOLITE_LICENSE_KEY="$(json_get geolite_license_key)"
INITIAL_API_KEY_CFG="$(json_get initial_api_key)"

DB_DRIVER="$(json_get db_driver)"; [ -n "${DB_DRIVER}" ] || DB_DRIVER="sqlite"
DB_HOST="$(json_get db_host)"
DB_PORT_RAW="$(json_get db_port)"; [ -n "${DB_PORT_RAW}" ] || DB_PORT_RAW="0"
DB_NAME="$(json_get db_name)"; [ -n "${DB_NAME}" ] || DB_NAME="shlink"
DB_USER="$(json_get db_user)"
DB_PASSWORD="$(json_get db_password)"

TIMEZONE="$(json_get timezone)"; [ -n "${TIMEZONE}" ] || TIMEZONE="UTC"
TRUSTED_PROXIES="$(json_get trusted_proxies)"

# --- Pflicht ---
if [ -z "${DEFAULT_DOMAIN}" ]; then
  echo "[ERROR] 'default_domain' ist erforderlich (z. B. s.example)."
  exit 10
fi

# --- Persistenz /etc/shlink -> /data/shlink ---
mkdir -p /data/shlink
if [ ! -L /etc/shlink ]; then
  if [ -e /etc/shlink ] && [ ! -L /etc/shlink ]; then
    rm -rf /etc/shlink
  fi
  ln -s /data/shlink /etc/shlink
fi

# --- API-Key bestimmen und IM KLARTEXT INS LOG schreiben ---
API_KEY_TO_USE=""
if [ -n "${INITIAL_API_KEY_CFG}" ]; then
  # GUI-Key verwenden
  API_KEY_TO_USE="${INITIAL_API_KEY_CFG}"
  printf "%s" "${API_KEY_TO_USE}" > "${API_KEY_FILE}" || true
  echo "[INFO] API-Key (Klartext, aus GUI): ${API_KEY_TO_USE}"
else
  if [ -s "${API_KEY_FILE}" ]; then
    # Bereits einmal erzeugt -> aus Datei lesen (nur intern), ins Log schreiben
    API_KEY_TO_USE="$(cat "${API_KEY_FILE}")"
    echo "[INFO] API-Key (Klartext, bereits erzeugt): ${API_KEY_TO_USE}"
  else
    # Noch kein Key -> jetzt über CLI erzeugen und direkt loggen
    echo "[INFO] Erzeuge neuen API-Key über Shlink CLI ..."
    # Name vergeben, damit man ihn später in der Liste erkennt
    GENERATED_LINE="$(shlink api-key:generate --name=ha_admin 2>/dev/null || true)"
    # Die CLI druckt den Key im Klartext; wir extrahieren robust: letztes "UUID/Hex"-ähnliches Token
    API_KEY_TO_USE="$(printf "%s" "${GENERATED_LINE}" | awk '{print $NF}' | tr -d '\r\n')"
    if [ -z "${API_KEY_TO_USE}" ]; then
      # Fallback: UUID
      API_KEY_TO_USE="$(cat /proc/sys/kernel/random/uuid 2>/dev/null || php -r 'echo bin2hex(random_bytes(16));')"
      echo "[WARN] Konnte CLI-Ausgabe nicht lesen, verwende Fallback-Key."
      # Diesen Fallback auch in Shlink persistieren:
      shlink api-key:disable "${API_KEY_TO_USE}" >/dev/null 2>&1 || true # no-op
    fi
    printf "%s" "${API_KEY_TO_USE}" > "${API_KEY_FILE}" || true
    echo "[INFO] API-Key (Klartext, neu erzeugt): ${API_KEY_TO_USE}"
  fi
fi

# --- ENV für Shlink setzen (gem. Doku) ---
export DEFAULT_DOMAIN="${DEFAULT_DOMAIN}"                 # Pflicht
export IS_HTTPS_ENABLED="${IS_HTTPS_ENABLED:-true}"       # Pflicht
export INITIAL_API_KEY="${API_KEY_TO_USE}"                # wird nur beim allerersten Start übernommen
export TIMEZONE="${TIMEZONE}"

# Optional
[ -n "${GEOLITE_LICENSE_KEY}" ] && export GEOLITE_LICENSE_KEY="${GEOLITE_LICENSE_KEY}"
[ -n "${TRUSTED_PROXIES}" ] && export TRUSTED_PROXIES="${TRUSTED_PROXIES}"

# DB-Port je Treiber
DB_PORT="${DB_PORT_RAW}"
if [ "${DB_PORT}" = "0" ] || [ -z "${DB_PORT}" ]; then
  case "${DB_DRIVER}" in
    mysql|maria) DB_PORT="3306" ;;
    postgres)    DB_PORT="5432" ;;
    mssql)       DB_PORT="1433" ;;
    *)           DB_PORT="0" ;;
  esac
fi

# Externe DB
case "${DB_DRIVER}" in
  mysql|maria|postgres|mssql)
    export DB_DRIVER="${DB_DRIVER}" DB_HOST="${DB_HOST}" DB_PORT="${DB_PORT}" \
           DB_NAME="${DB_NAME}" DB_USER="${DB_USER}" DB_PASSWORD="${DB_PASSWORD}"
    ;;
  sqlite|"")
    echo "[INFO] Verwende interne SQLite-Datenbank (für Produktion externe DB empfohlen)."
    ;;
  *)
    echo "[ERROR] Unbekannter db_driver: ${DB_DRIVER} (sqlite|mysql|maria|postgres|mssql)"
    exit 11
    ;;
esac

# --- WICHTIG: Key im Log ist dein Klartext-Key für den Header 'X-Api-Key' ---
echoecho "[INFO] Verwende für REST-Aufrufe den Header: X-Api-Key: ${API_KEY_TO_USE}"

# --- Upstream-Entrypoint starten (liegt im Workdir /etc/shlink) ---
if [ -x "./docker-entrypoint.sh" ]; then
  exec /bin/sh ./docker-entrypoint.sh
else
  echo "[ERROR] Upstream-Entrypoint ./docker-entrypoint.sh nicht gefunden."
  exit 12


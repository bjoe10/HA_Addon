
#!/usr/bin/env bash
# HA_Addon/shlink/run.sh
set -euo pipefail

CONFIG_PATH="/data/options.json"

echo "[INFO] Shlink Server Add-on startet. Lese Optionen aus ${CONFIG_PATH}"

# --- Optionen lesen ---
DEFAULT_DOMAIN="$(jq -r '.default_domain // empty' "$CONFIG_PATH")"
IS_HTTPS_ENABLED="$(jq -r '.is_https_enabled // true' "$CONFIG_PATH")"
GEOLITE_LICENSE_KEY="$(jq -r '.geolite_license_key // empty' "$CONFIG_PATH")"
INITIAL_API_KEY="$(jq -r '.initial_api_key // empty' "$CONFIG_PATH")"

DB_DRIVER="$(jq -r '.db_driver // "sqlite"' "$CONFIG_PATH")"
DB_HOST="$(jq -r '.db_host // empty' "$CONFIG_PATH")"
DB_PORT_RAW="$(jq -r '.db_port // 0' "$CONFIG_PATH")"
DB_NAME="$(jq -r '.db_name // "shlink"' "$CONFIG_PATH")"
DB_USER="$(jq -r '.db_user // empty' "$CONFIG_PATH")"
DB_PASSWORD="$(jq -r '.db_password // empty' "$CONFIG_PATH")"

TIMEZONE="$(jq -r '.timezone // "UTC"' "$CONFIG_PATH")"
TRUSTED_PROXIES="$(jq -r '.trusted_proxies // empty' "$CONFIG_PATH")"

# --- Pflicht-/Sinnprüfungen ---
if [ -z "$DEFAULT_DOMAIN" ]; then
  echo "[ERROR] 'default_domain' ist erforderlich (z. B. s.example)."
  exit 10
fi

# DB-Standardport pro Treiber
DB_PORT="$DB_PORT_RAW"
if [ "$DB_PORT" = "0" ] || [ -z "$DB_PORT" ]; then
  case "$DB_DRIVER" in
    mysql|maria) DB_PORT=3306 ;;
    postgres)    DB_PORT=5432 ;;
    mssql)       DB_PORT=1433 ;;
    *)           DB_PORT=0 ;; # sqlite benötigt keinen Port
  esac
fi

# --- Persistenz (/etc/shlink -> /data/shlink) ---
mkdir -p /data/shlink
if [ ! -L /etc/shlink ]; then
  if [ -e /etc/shlink ] && [ ! -L /etc/shlink ]; then
    rm -rf /etc/shlink
  fi
  ln -s /data/shlink /etc/shlink
  echo "[INFO] /etc/shlink → /data/shlink verlinkt (persistente Daten)."
fi

# --- ENV für Shlink setzen (gem. offizieller Doku) ---
export DEFAULT_DOMAIN="$DEFAULT_DOMAIN"      # Pflicht
export IS_HTTPS_ENABLED="$IS_HTTPS_ENABLED"  # Pflicht
export TIMEZONE="$TIMEZONE"

# GeoLite Lizenzschlüssel (optional; ohne Key ist Geolokalisierung deaktiviert)
if [ -n "$GEOLITE_LICENSE_KEY" ]; then
  export GEOLITE_LICENSE_KEY="$GEOLITE_LICENSE_KEY"
fi

# Initialer Admin-API-Key (optional)
if [ -n "$INITIAL_API_KEY" ]; then
  export INITIAL_API_KEY="$INITIAL_API_KEY"
fi

# Trusted Proxies (optional, z.B. bei Reverse Proxies)
if [ -n "$TRUSTED_PROXIES" ]; then
  export TRUSTED_PROXIES="$TRUSTED_PROXIES"
fi

# Externe DB konfigurieren
case "$DB_DRIVER" in
  mysql|maria|postgres|mssql)
    export DB_DRIVER="$DB_DRIVER"
    export DB_HOST="$DB_HOST"
    export DB_PORT="$DB_PORT"
    export DB_NAME="$DB_NAME"
    export DB_USER="$DB_USER"
    export DB_PASSWORD="$DB_PASSWORD"

    if [ -z "$DB_HOST" ] || [ -z "$DB_USER" ] || [ -z "$DB_PASSWORD" ]; then
      echo "[WARN] Externe DB gewählt ($DB_DRIVER), aber Host/User/Passwort unvollständig."
    fi
    ;;
  sqlite|"")
    echo "[INFO] Verwende interne SQLite-Datenbank (für Produktion externe DB empfohlen)."
    ;;
  *)
    echo "[ERROR] Unbekannter db_driver: $DB_DRIVER (erlaubt: sqlite|mysql|maria|postgres|mssql)"
    exit 11
    ;;
esac

# --- Shlink starten: Upstream-Entrypoint nutzen ---
echo "[INFO] Starte Shlink Server ..."
if [ -x /usr/local/bin/docker-entrypoint.sh ]; then
  exec /usr/local/bin/docker-entrypoint.sh
elif [ -x /docker-entrypoint.sh ]; then
  exec /docker-entrypoint.sh
else
  # Fallback: versuche RoadRunner (Shlink nutzt RR im Container)
  echo "[WARN] Upstream-Entrypoint nicht gefunden. Versuche RoadRunner..."
  if command -v rr >/dev/null 2>&1; then
    exec rr serve -c /etc/rr.yaml
  else
    echo "[ERROR] Weder Entrypoint noch RoadRunner gefunden."
    exit 12
  fi
fi
``

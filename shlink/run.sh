#!/bin/sh

CONFIG_PATH=/data/options.json

echo "Starte Shlink Add-on mit SQLite-Konfiguration..."

# --- 1. HA Konfiguration lesen ---
DOMAIN=$(jq --raw-output '.default_domain' $CONFIG_PATH)
HTTPS=$(jq --raw-output '.is_https' $CONFIG_PATH)
GEO_KEY=$(jq --raw-output '.geolite_license_key // empty' $CONFIG_PATH)
# NEU: Trusted Hosts und API Key lesen
TRUSTED_HOSTS=$(jq --raw-output '.trusted_hosts // empty' $CONFIG_PATH)
INITIAL_API_KEY=$(jq --raw-output '.initial_api_key // empty' $CONFIG_PATH)

# --- 2. Environment Variablen setzen ---
export DEFAULT_DOMAIN="$DOMAIN"
export IS_HTTPS_ENABLED="$HTTPS"
export GEOLITE_LICENSE_KEY="$GEO_KEY"

# NEU: Export für CORS und optionalen API Key
export SHLINK_TRUSTED_HOSTS="$TRUSTED_HOSTS"
export INITIAL_API_KEY="$INITIAL_API_KEY"

# SQLite Standardwerte (bleiben gleich)
export DB_DRIVER="sqlite"
export DB_NAME="/data/shlink_db.sqlite"

echo "Domain: $DOMAIN (HTTPS: $HTTPS)"
echo "Trusted Hosts (CORS): $SHLINK_TRUSTED_HOSTS"

# --- 3. Datenbank-Check ---
if [ ! -f "/data/shlink_db.sqlite" ]; then
    echo "SQLite Datenbankdatei wird im persistenten Speicher (/data) angelegt."
    touch /data/shlink_db.sqlite
fi

# --- 4. Server Start ---
echo "Shlink Umgebung ist konfiguriert. Starte Server..."

exec /usr/local/bin/docker-entrypoint.sh

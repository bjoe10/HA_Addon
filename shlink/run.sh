#!/usr/bin/with-contenv bashio

# Wir nutzen hier "bashio", das macht das Lesen der Config viel einfacher als jq!
# Bashio ist in den meisten HA Base-Images dabei. Da wir das Shlink-Image nutzen,
# müssen wir improvisieren oder bei jq bleiben.
# Um es einfach und kompatibel mit dem vorherigen Dockerfile zu halten, nutzen wir wieder jq.

CONFIG_PATH=/data/options.json

echo "Lese Konfiguration aus Home Assistant..."

# 1. Basis-Einstellungen
DOMAIN=$(jq --raw-output '.default_domain' $CONFIG_PATH)
HTTPS=$(jq --raw-output '.is_https' $CONFIG_PATH)
GEO_KEY=$(jq --raw-output '.geolite_license_key // empty' $CONFIG_PATH)

# Export für Shlink
export DEFAULT_DOMAIN="$DOMAIN"
export IS_HTTPS_ENABLED="$HTTPS"
export GEOLITE_LICENSE_KEY="$GEO_KEY"

# 2. Datenbank-Einstellungen
DB_DRIVER=$(jq --raw-output '.db_driver' $CONFIG_PATH)

if [ "$DB_DRIVER" == "sqlite" ]; then
    echo "Nutze interne SQLite Datenbank."
    export DB_DRIVER="sqlite"
    export DB_NAME="/data/shlink_db.sqlite"
else
    # Für MySQL (MariaDB) oder Postgres
    echo "Nutze externe Datenbank: $DB_DRIVER"
    export DB_DRIVER="$DB_DRIVER"
    export DB_USER=$(jq --raw-output '.db_user' $CONFIG_PATH)
    export DB_PASSWORD=$(jq --raw-output '.db_password' $CONFIG_PATH)
    export DB_HOST=$(jq --raw-output '.db_host' $CONFIG_PATH)
    # Standard DB Name für Externe
    export DB_NAME="shlink" 
fi

# Prüfen ob initialer Setup nötig ist (nur bei SQLite wichtig für die Datei)
if [ "$DB_DRIVER" == "sqlite" ] && [ ! -f "/data/shlink_db.sqlite" ]; then
    echo "SQLite Datei wird neu angelegt..."
    touch /data/shlink_db.sqlite
fi

echo "Starte Shlink auf Port 8080..."

# Original Entrypoint von Shlink aufrufen
exec /usr/local/bin/docker-entrypoint.sh

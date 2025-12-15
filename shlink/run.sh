#!/bin/sh

# Pfad zur Home Assistant Konfigurationsdatei
CONFIG_PATH=/data/options.json

echo "Starte Shlink Add-on mit SQLite-Konfiguration..."

# --- 1. HA Konfiguration lesen ---
# Lesen der Werte aus der HA-Konfiguration (config.yaml > options)
DOMAIN=$(jq --raw-output '.default_domain' $CONFIG_PATH)
HTTPS=$(jq --raw-output '.is_https' $CONFIG_PATH)
# Die "// empty" Syntax stellt sicher, dass es keinen Fehler gibt, wenn der Schlüssel leer ist
GEO_KEY=$(jq --raw-output '.geolite_license_key // empty' $CONFIG_PATH)

# --- 2. Environment Variablen setzen ---
# Exportieren als Environment-Variablen, die von Shlink gelesen werden
export DEFAULT_DOMAIN="$DOMAIN"
export IS_HTTPS_ENABLED="$HTTPS"
export GEOLITE_LICENSE_KEY="$GEO_KEY"

# Wichtig: Festlegen der SQLite-Umgebungsvariablen im persistenten Speicher
export DB_DRIVER="sqlite"
export DB_NAME="/data/shlink_db.sqlite"

echo "Domain: $DOMAIN (HTTPS: $HTTPS)"
echo "Datenbank: SQLite (/data/shlink_db.sqlite)"

# --- 3. Datenbank-Check ---
# Prüfen ob die Datenbankdatei existiert, falls nicht, erstellen (wichtig für den ersten Start)
if [ ! -f "/data/shlink_db.sqlite" ]; then
    echo "SQLite Datenbankdatei wird im persistenten Speicher (/data) angelegt."
    touch /data/shlink_db.sqlite
fi

# --- 4. Server Start ---
echo "Shlink Umgebung ist konfiguriert. Starte Server..."

# Starten des offiziellen Shlink Docker Entrypoints
exec /usr/local/bin/docker-entrypoint.sh

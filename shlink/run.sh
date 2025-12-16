#!/bin/bash

# Pfad zur Home Assistant Konfiguration
CONFIG_PATH=/data/options.json

echo "Starte Shlink Addon..."

# 1. Konfiguration aus der GUI auslesen
export DEFAULT_DOMAIN=$(jq --raw-output '.default_domain' $CONFIG_PATH)
GEO_KEY=$(jq --raw-output '.geolite_license_key // empty' $CONFIG_PATH)
DISABLE_TRACKING=$(jq --raw-output '.disable_track_param // empty' $CONFIG_PATH)

# GeoLite Key setzen
if [ ! -z "$GEO_KEY" ]; then
    export GEOLITE_LICENSE_KEY="$GEO_KEY"
fi

# Tracking Parameter deaktivieren
if [ ! -z "$DISABLE_TRACKING" ]; then
    export DISABLE_TRACK_PARAM="$DISABLE_TRACKING"
fi

# 2. Datenbank Konfiguration (SQLite im persistenten /data Ordner)
export DB_DRIVER=sqlite
export DB_CONNECTION=sqlite
export DB_DATABASE="/data/database.sqlite"

# Sicherstellen, dass die Berechtigungen stimmen
touch "$DB_DATABASE"
chmod 777 "$DB_DATABASE"

echo "Nutze Datenbank unter: $DB_DATABASE"

# 3. Initialisierung prüfen
DB_SIZE=$(wc -c < "$DB_DATABASE")

if [ "$DB_SIZE" -eq 0 ]; then
    echo "--- Neuinstallation erkannt (Datenbank leer). Initialisiere... ---"
    
    # Datenbank erstellen
    php /etc/shlink/bin/cli db:create
    php /etc/shlink/bin/cli db:migrate

    echo " "
    echo "################################################################"
    echo "#   ERSTELLUNG DES API KEYS                                    #"
    echo "#   Bitte kopiere den Key zwischen den Anführungszeichen!      #"
    echo "################################################################"
    
    php /etc/shlink/bin/cli api-key:generate
    
    echo "################################################################"
    echo " "
else
    echo "Datenbank existiert bereits ($DB_SIZE bytes). Überspringe Initialisierung."
fi

# 4. Server Starten (Angepasst für Shlink v4 / FrankenPHP)
echo "Starte Shlink Server Prozess..."

# Wir prüfen zuerst, ob es ein Standard-Entrypoint-Skript gibt (für Abwärtskompatibilität)
if [ -f "/usr/local/bin/docker-entrypoint.sh" ]; then
    echo "Standard Entrypoint gefunden. Führe aus..."
    exec /usr/local/bin/docker-entrypoint.sh
else
    echo "Kein Entrypoint-Skript gefunden. Starte FrankenPHP (Shlink v4 Standard)..."
    # Das ist der neue Startbefehl für Shlink v4+
    exec frankenphp run --config /etc/caddy/Caddyfile
fi

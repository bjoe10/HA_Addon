#!/bin/bash

# Pfad zur Home Assistant Konfiguration
CONFIG_PATH=/data/options.json

echo "Starte Shlink Addon..."

# 1. Konfiguration aus der GUI auslesen
export DEFAULT_DOMAIN=$(jq --raw-output '.default_domain' $CONFIG_PATH)
GEO_KEY=$(jq --raw-output '.geolite_license_key // empty' $CONFIG_PATH)
DISABLE_TRACKING=$(jq --raw-output '.disable_track_param // empty' $CONFIG_PATH)

if [ ! -z "$GEO_KEY" ]; then
    export GEOLITE_LICENSE_KEY="$GEO_KEY"
fi

if [ ! -z "$DISABLE_TRACKING" ]; then
    export DISABLE_TRACK_PARAM="$DISABLE_TRACKING"
fi

# 2. Datenbank Konfiguration (SQLite im persistenten /data Ordner)
export DB_DRIVER=sqlite
export DB_CONNECTION=sqlite
export DB_DATABASE="/data/database.sqlite"

touch "$DB_DATABASE"
chmod 777 "$DB_DATABASE"

echo "Nutze Datenbank unter: $DB_DATABASE"

# 3. Initialisierung prüfen und API Key generieren
DB_SIZE=$(wc -c < "$DB_DATABASE")

if [ "$DB_SIZE" -eq 0 ]; then
    echo "--- Neuinstallation erkannt (Datenbank leer). Initialisiere... ---"
    
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

# 4. SERVER STARTEN (ENDGÜLTIGE LÖSUNG)
echo "Starte Shlink Server Prozess..."

# Der korrekte Pfad wird im Shlink Image in die Variable FRANKENPHP_PATH gelegt.
if [ -z "$FRANKENPHP_PATH" ]; then
    echo "FEHLER: Umgebungsvariable FRANKENPHP_PATH nicht gesetzt. Das Image ist nicht kompatibel."
    exit 1
else
    echo "FrankenPHP Pfad ($FRANKENPHP_PATH) gefunden. Starte Server..."
    # Wir führen den Pfad in der Variable aus.
    exec "$FRANKENPHP_PATH" run --config /etc/caddy/Caddyfile
fi

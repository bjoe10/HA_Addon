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

# 3. Initialisierung prüfen
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

# 4. Server Starten (FINALE ANPASSUNG)
echo "Starte Shlink Server Prozess..."

# Wir verwenden den wahrscheinlichsten Pfad für die FrankenPHP Binary in Alpine-basierten Images.
# In Shlink v4 ist dies der exakte Befehl, den Docker ausführt, um den Server zu starten.

if [ -f "/usr/local/bin/frankenphp" ]; then
    echo "FrankenPHP Binary gefunden. Starte Shlink Server über den direkten Befehl."
    # Das ist der Startbefehl für Shlink v4+
    exec /usr/local/bin/frankenphp run --config /etc/caddy/Caddyfile
else
    # Fallback, falls der Pfad nicht stimmt (sehr unwahrscheinlich bei v4)
    echo "FEHLER: FrankenPHP Binary nicht unter /usr/local/bin/frankenphp gefunden."
    echo "Der Container ist möglicherweise nicht das erwartete Shlink v4 Image."
    # Wir lassen den Container abstürzen, um den Fehler sichtbar zu machen.
    exit 1
fi

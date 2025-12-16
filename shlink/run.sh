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

# Sicherstellen, dass die Berechtigungen stimmen (Home Assistant spezifisch)
touch "$DB_DATABASE"
chmod 777 "$DB_DATABASE"

echo "Nutze Datenbank unter: $DB_DATABASE"

# 3. Initialisierung prüfen
# Wir prüfen, ob die Datenbank Tabellen enthält, indem wir die Größe prüfen oder ob sie neu ist.
# Da 'touch' die Datei oben anlegt, prüfen wir, ob sie leer ist.
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
    
    # Wir führen den Befehl direkt aus, damit er sauber im Log landet
    php /etc/shlink/bin/cli api-key:generate
    
    echo "################################################################"
    echo " "
else
    echo "Datenbank existiert bereits ($DB_SIZE bytes). Überspringe Initialisierung."
fi

# 4. Server Starten
echo "Starte Shlink Server Prozess..."

# KORREKTUR: Der Pfad ist /docker-entrypoint.sh (im Root), nicht in /usr/local/bin
if [ -f "/docker-entrypoint.sh" ]; then
    exec /docker-entrypoint.sh
else
    # Fallback, falls sich das Image ändert: Wir starten den Server direkt
    echo "Entrypoint nicht gefunden, starte RoadRunner direkt..."
    exec php -d variables_order=EGPCS /etc/shlink/vendor/bin/rr serve -c /etc/shlink/.rr.yaml
fi

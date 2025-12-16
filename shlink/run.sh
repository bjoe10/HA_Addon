#!/bin/bash

# Pfad zur Home Assistant Konfiguration
CONFIG_PATH=/data/options.json

echo "Starte Shlink Addon..."

# 1. Konfiguration aus der GUI auslesen (jq)
export DEFAULT_DOMAIN=$(jq --raw-output '.default_domain' $CONFIG_PATH)
GEO_KEY=$(jq --raw-output '.geolite_license_key // empty' $CONFIG_PATH)
DISABLE_TRACKING=$(jq --raw-output '.disable_track_param // empty' $CONFIG_PATH)

# GeoLite Key setzen, falls vorhanden
if [ ! -z "$GEO_KEY" ]; then
    export GEOLITE_LICENSE_KEY="$GEO_KEY"
fi

# Tracking Parameter deaktivieren, falls gewünscht
if [ ! -z "$DISABLE_TRACKING" ]; then
    export DISABLE_TRACK_PARAM="$DISABLE_TRACKING"
fi

# 2. Datenbank Konfiguration (SQLite im persistenten /data Ordner)
# Home Assistant speichert persistente Daten in /data.
# Wir zwingen Shlink, SQLite zu nutzen und die DB dort abzulegen.
export DB_DRIVER=sqlite
export DB_CONNECTION=sqlite
export DB_DATABASE="/data/database.sqlite"

echo "Nutze Datenbank unter: $DB_DATABASE"

# 3. Initialisierung und API Key Logik
# Wir prüfen, ob die Datenbank bereits existiert. Wenn nicht, ist es eine Neuinstallation.
FIRST_RUN=false
if [ ! -f "$DB_DATABASE" ]; then
    FIRST_RUN=true
    echo "--- Neuinstallation erkannt. Initialisiere Datenbank... ---"
    # Datenbank erstellen (nutzt das interne CLI von Shlink)
    php /etc/shlink/bin/cli db:create
    php /etc/shlink/bin/cli db:migrate
fi

# 4. Server Starten
# Wir starten den Server im Hintergrund, um ggf. noch Befehle auszuführen,
# oder wir übergeben direkt an den originalen Startbefehl.
# Da wir den API Key sehen wollen, generieren wir ihn, wenn es der erste Start ist.

if [ "$FIRST_RUN" = true ]; then
    echo "Generiere initialen API Key..."
    NEW_KEY=$(php /etc/shlink/bin/cli api-key:generate)
    
    echo " "
    echo "################################################################"
    echo "#                                                              #"
    echo "#   DEIN SHLINK API KEY:                                       #"
    echo "#   $NEW_KEY"
    echo "#                                                              #"
    echo "#   (Kopiere diesen Key, um dich mit Clients zu verbinden)     #"
    echo "#                                                              #"
    echo "################################################################"
    echo " "
else
    echo "System bereits installiert. Um einen neuen API Key zu generieren,"
    echo "nutze die Konsole im Container: php bin/cli api-key:generate"
fi

# 5. Originalen Entrypoint ausführen (startet Swoole Server)
echo "Starte Shlink Server Prozess..."
exec /usr/local/bin/docker-entrypoint.sh

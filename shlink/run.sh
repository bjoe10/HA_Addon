#!/bin/bash

# Pfad zur Home Assistant Konfiguration
CONFIG_PATH=/data/options.json

echo "Starte Shlink Addon..."

# 1. Konfiguration aus der GUI auslesen (Bleibt unverändert)
export DEFAULT_DOMAIN=$(jq --raw-output '.default_domain' $CONFIG_PATH)
GEO_KEY=$(jq --raw-output '.geolite_license_key // empty' $CONFIG_PATH)
DISABLE_TRACKING=$(jq --raw-output '.disable_track_param // empty' $CONFIG_PATH)

if [ ! -z "$GEO_KEY" ]; then
    export GEOLITE_LICENSE_KEY="$GEO_KEY"
fi

if [ ! -z "$DISABLE_TRACKING" ]; then
    export DISABLE_TRACK_PARAM="$DISABLE_TRACKING"
fi

# 2. Datenbank Konfiguration (Bleibt unverändert)
export DB_DRIVER=sqlite
export DB_CONNECTION=sqlite
export DB_DATABASE="/data/database.sqlite"

touch "$DB_DATABASE"
chmod 777 "$DB_DATABASE"

echo "Nutze Datenbank unter: $DB_DATABASE"

# 3. Initialisierung prüfen und API Key generieren (Bleibt unverändert)
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

# 4. SERVER STARTEN (ENDGÜLTIGE LÖSUNG MIT IMAGE-ENTRYPOINT)

# Wir müssen den Entrypoint des Images ausführen, um die Umgebung einzurichten.
echo "Führe den Shlink Image-Entrypoint aus, um die Umgebung zu initialisieren..."
# Der offizielle Shlink v4 Entrypoint liegt unter /entrypoint.sh und setzt FRANKENPHP_PATH
if [ -f "/entrypoint.sh" ]; then
    # Wir führen es aus, aber ohne den 'serve'-Befehl, da es sonst sofort startet
    # Wir nutzen 'sh -c' um das Skript auszuführen
    sh /entrypoint.sh
    echo "Image-Entrypoint erfolgreich ausgeführt."
else
    echo "WARNUNG: /entrypoint.sh nicht gefunden. Fahren Sie ohne Image-Entrypoint fort."
fi

echo "Starte Shlink Server Prozess..."

# Nachdem der Entrypoint gelaufen ist, MUSS FRANKENPHP_PATH gesetzt sein.
if [ -z "$FRANKENPHP_PATH" ]; then
    # Fallback, wenn der Entrypoint nicht funktioniert hat
    echo "FEHLER: FRANKENPHP_PATH ist immer noch nicht gesetzt. Versuche den direkten Startpfad."
    # Wir verwenden den Pfad, der in der Vergangenheit funktioniert hat (meistens /usr/bin)
    exec /usr/bin/frankenphp run --config /etc/caddy/Caddyfile
else
    echo "FrankenPHP Pfad ($FRANKENPHP_PATH) gefunden. Starte Server..."
    exec "$FRANKENPHP_PATH" run --config /etc/caddy/Caddyfile
fi

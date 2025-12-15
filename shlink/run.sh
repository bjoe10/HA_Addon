#!/bin/sh

# Home Assistant speichert Optionen in /data/options.json
CONFIG_PATH=/data/options.json

echo "Starte Shlink Add-on..."

# Lesen der Werte aus der HA-Konfiguration
DEFAULT_DOMAIN=$(jq --raw-output '.default_domain' $CONFIG_PATH)
IS_HTTPS=$(jq --raw-output '.is_https' $CONFIG_PATH)

echo "Konfiguriere Domain: $DEFAULT_DOMAIN"

# Exportieren als Environment-Variablen für Shlink
export DEFAULT_DOMAIN="$DEFAULT_DOMAIN"
export IS_HTTPS_ENABLED="$IS_HTTPS"
export GEOLITE_LICENSE_KEY="" # Optional: Hier könnte man noch einen Key via Config einbauen

# WICHTIG: Prüfen ob die Datenbank existiert, sonst initialisieren
if [ ! -f "/data/shlink_db.sqlite" ]; then
    echo "Datenbank wird initialisiert..."
    # Initialer Shlink Befehl, falls nötig, passiert oft automatisch beim ersten Start im Container
fi

# Da wir im Dockerfile USER root waren, wechseln wir für den Start 
# (optional, aber sicherer) oder lassen Shlink als root laufen (einfacher für den Anfang).
# Der offizielle Container nutzt entrypoint-Logik. Wir rufen diese nun auf.

# Starten des Servers (Standard Command des Shlink Images imitieren)
exec /usr/local/bin/docker-entrypoint.sh

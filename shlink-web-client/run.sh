#!/bin/sh

CONFIG_PATH=/data/options.json

echo "Starte Shlink Web Client Add-on..."

# Lesen der API-URL aus der HA-Konfiguration
API_URL=$(jq --raw-output '.shlink_api_url' $CONFIG_PATH)

echo "Konfiguriere API-URL für Web Client: $API_URL"

# Pfad zur Nginx-Wurzel
WEB_ROOT=/usr/share/nginx/html

# Erstellen der config.js-Datei, um die API-URL zu injizieren
# Dies ist die korrekte Methode für diesen Client.
echo "window.SHLINK_SERVER_URL = \"$API_URL\";" > "$WEB_ROOT/assets/config.js"

if [ -f "$WEB_ROOT/assets/config.js" ]; then
    echo "config.js erfolgreich erstellt und URL injiziert."
else
    echo "FEHLER: Konnte config.js nicht erstellen. Prüfe Pfade."
    exit 1
fi

# Starten des Nginx-Servers, der das Frontend ausliefert
echo "Starte Nginx Webserver auf Port 8081..."
exec nginx -g "daemon off;"

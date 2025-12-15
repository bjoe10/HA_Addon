#!/bin/sh

CONFIG_PATH=/data/options.json

echo "Starte Shlink Web Client Add-on..."

# Lesen der API-URL
API_URL=$(jq --raw-output '.shlink_api_url' $CONFIG_PATH)

echo "Konfiguriere API-URL für Web Client: $API_URL"

# Der Shlink Web Client nutzt eine environment-Variable, die im Nginx-Config gesetzt werden muss.
# Wir nutzen sed, um die URL in die JavaScript-Konfigurationsdatei des Clients einzufügen.
# Der Web Client erwartet die URL in der Form SHLINK_SERVER_URL=...
sed -i "s|// REPLACE_SERVER_URL|window.SHLINK_SERVER_URL = \"$API_URL\";|" /usr/share/nginx/html/assets/config.js

# Starten des Nginx-Servers, der das Frontend ausliefert
echo "Starte Nginx Webserver auf Port 8081..."
exec nginx -g "daemon off;"

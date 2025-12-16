
#!/bin/sh
set -e

CONFIG_PATH="/data/options.json"

# jq ist im Container installiert (siehe Dockerfile)
json() { jq -r "$1 // empty" "$CONFIG_PATH"; }

# -- Add-on Optionen auslesen --
DEFAULT_DOMAIN=$(json '.default_domain')
IS_HTTPS_ENABLED=$(json '.is_https_enabled')
GEOLITE_LICENSE_KEY=$(json '.geolite_license_key')
BASE_PATH=$(json '.base_path')
TIMEZONE=$(json '.timezone')
TRUSTED_PROXIES=$(json '.trusted_proxies')

DB_DRIVER=$(json '.db.driver')
DB_HOST=$(json '.db.host')
DB_PORT=$(json '.db.port')
DB_NAME=$(json '.db.name')
DB_USER=$(json '.db.user')
DB_PASSWORD=$(json '.db.password')

AUTO_GENERATE_API_KEY=$(json '.auto_generate_api_key')
API_KEY_NAME=$(json '.api_key_name')

# -- Shlink erwartet diese ENV-Variablen --
# (siehe Shlink-Docker-Doku / Environment-Variablen)
export DEFAULT_DOMAIN IS_HTTPS_ENABLED GEOLITE_LICENSE_KEY BASE_PATH TIMEZONE TRUSTED_PROXIES
export DB_DRIVER DB_HOST DB_PORT DB_NAME DB_USER DB_PASSWORD

echo "[INFO] Shlink Add-on startet ..."
echo "[INFO] Domain=${DEFAULT_DOMAIN} HTTPS=${IS_HTTPS_ENABLED} DB=${DB_DRIVER}@${DB_HOST}:${DB_PORT}/${DB_NAME}"
echo "[INFO] BasePath=${BASE_PATH:-/} Timezone=${TIMEZONE:-UTC}"

# -- Initialen API-Key erzeugen und ins Log schreiben --
if [ "${AUTO_GENERATE_API_KEY}" != "false" ]; then
  if [ ! -f /data/api_key.txt ]; then
    echo "[INFO] Erzeuge initialen API-Key ..."
    KEY_NAME=${API_KEY_NAME:-homeassistant}

    # Erzeuge nur, wenn noch keiner mit diesem Namen existiert
    if ! shlink api-key:list 2>/dev/null | grep -q " ${KEY_NAME} "; then
      API_KEY=$(
        shlink api-key:generate --name="${KEY_NAME}" --no-interaction \
        | tail -n1 | tr -d ' \r\n'
      )
      if [ -n "${API_KEY}" ]; then
        echo "${API_KEY}" > /data/api_key.txt
        chmod 600 /data/api_key.txt
        echo "[INFO] Initialer API-Key (auch gespeichert unter /data/api_key.txt): ${API_KEY}"
      else
        echo "[WARN] Konnte den API-Key nicht aus der Ausgabe parsen. Führe 'shlink api-key:generate' manuell im Container aus."
      fi
    else
      echo "[INFO] API-Key mit Name '${KEY_NAME}' existiert bereits. Überspringe Generierung."
    fi
  else
    echo "[INFO] Bereits vorhandener API-Key in /data/api_key.txt gefunden."
  fi
fi

## -- Shlink-Server über den Original-Entrypoint starten (RoadRunner, Port 8080) --
# Der Entrypoint liegt im Image unter /etc/shlink/docker-entrypoint.sh


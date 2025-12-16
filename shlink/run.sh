
#!/bin/sh
# Liest /data/options.json per PHP, setzt passende ENV-Variablen,
# erzeugt bei Bedarf einen initialen API-Key und startet Shlink.
set -e

OPTIONS="/data/options.json"

php_json() {
  # php_json "pfad.zum.schlüssel"
  php -r '
    $p="/data/options.json";
    $j = file_exists($p) ? json_decode(file_get_contents($p), true) : [];
    function get($a,$path){
      $keys = explode(".", $path);
      $v = $a;
      foreach ($keys as $k) {
        if (!is_array($v) || !array_key_exists($k, $v)) { $v = null; break; }
        $v = $v[$k];
      }
      if (is_bool($v)) { echo $v ? "true" : "false"; }
      else { echo $v === null ? "" : (string)$v; }
    }
    get($j, $argv[1] ?? "");
  ' "$1"
}

# -- GUI-Optionen lesen und als ENV exportieren -------------------------------
export DEFAULT_DOMAIN="$(php_json 'default_domain')"
export IS_HTTPS_ENABLED="$(php_json 'is_https_enabled')"
export GEOLITE_LICENSE_KEY="$(php_json 'geolite_license_key')"
export BASE_PATH="$(php_json 'base_path')"
export TIMEZONE="$(php_json 'timezone')"
export TRUSTED_PROXIES="$(php_json 'trusted_proxies')"

export DB_DRIVER="$(php_json 'db.driver')"
export DB_HOST="$(php_json 'db.host')"
export DB_PORT="$(php_json 'db.port')"
export DB_NAME="$(php_json 'db.name')"
export DB_USER="$(php_json 'db.user')"
export DB_PASSWORD="$(php_json 'db.password')"

AUTO_GEN="$(php_json 'auto_generate_api_key')"
API_KEY_NAME="$(php_json 'api_key_name')"
INITIAL_API_KEY_OPT="$(php_json 'initial_api_key')"

echo "[INFO] Shlink Add-on startet ..."
echo "[INFO] Domain=${DEFAULT_DOMAIN} HTTPS=${IS_HTTPS_ENABLED} DB=${DB_DRIVER}@${DB_HOST}:${DB_PORT}/${DB_NAME}"
echo "[INFO] BasePath=${BASE_PATH:-/} Timezone=${TIMEZONE:-UTC}"

# -- Optional: Initialen API-Key über ENV setzen (ab Shlink 3.3 unterstütz) --
# Wenn 'initial_api_key' in der GUI gesetzt ist, nutzt Shlink ihn direkt.
if [ -n "${INITIAL_API_KEY_OPT}" ]; then
  export INITIAL_API_KEY="${INITIAL_API_KEY_OPT}"
  echo "[INFO] Initialer API-Key aus Option gesetzt: ${INITIAL_API_KEY_OPT}"
  echo "${INITIAL_API_KEY_OPT}" > /data/api_key.txt
  chmod 600 /data/api_key.txt
fi

# -- Falls kein initial_api_key gesetzt ist: API-Key einmalig generieren -------
if [ "${AUTO_GEN}" != "false" ] && [ ! -f /data/api_key.txt ]; then
  KEY_NAME="${API_KEY_NAME:-homeassistant}"

  # Nur erzeugen, wenn mit dem Namen nichts existiert
  if ! shlink api-key:list 2>/dev/null | grep -q " ${KEY_NAME} "; then
    echo "[INFO] Erzeuge initialen API-Key mit Name='${KEY_NAME}' ..."
    GEN_OUTPUT="$(shlink api-key:generate --name="${KEY_NAME}" --no-interaction || true)"

    # Robust: Nimm die letzte nicht-leere Zeile als Key (Shlink gibt den Key separat aus)
    API_KEY="$(echo "${GEN_OUTPUT}" | sed '/^\s*$/d' | tail -n1 | tr -d '\r\n')"

    if [ -n "${API_KEY}" ]; then
      echo "${API_KEY}" > /data/api_key.txt
      chmod 600 /data/api_key.txt
      echo "[INFO] Initialer API-Key (auch gespeichert unter /data/api_key.txt): ${API_KEY}"
    else
      echo "[WARN] Konnte den generierten API-Key nicht aus der Ausgabe ermitteln."
      echo "[HINT] Führe im Container 'shlink api-key:generate --name=${KEY_NAME}' manuell aus."
    fi
   else
    echo "[INFO] API-Key mit Name '${KEY_NAME}' existiert bereits – keine Neugenerierung."
  fi
fi

# -- Start: Shlink-Original-Entrypoint (RoadRunner auf Port 8080) -------------
# Die Shlink-Docker-Doku empfiehlt den Start über den mitgelieferten Entrypoint.


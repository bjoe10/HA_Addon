#!/bin/sh

# ==============================
# Immich Job Daemon
# ==============================
# Ziel:
# - Alle Jobs normal laufen lassen
# - Sicherstellen, dass OCR und smartSearch nie gleichzeitig aktiv sind
# - OCR darf immer warten
# ==============================

# Konfiguration aus Home Assistant options.json laden
API_KEY=$(jq -r '.API_KEY' /data/options.json)
IMMICH_URL=$(jq -r '.IMMICH_URL' /data/options.json)
POLL_INTERVAL=$(jq -r '.POLL_INTERVAL' /data/options.json)

URL="${IMMICH_URL}/api/jobs"

# Validierung
if [ -z "$API_KEY" ]; then
    echo "ERROR: API_KEY fehlt" >&2
    exit 1
fi

if ! echo "$POLL_INTERVAL" | grep -qE '^[1-9][0-9]*$'; then
    echo "ERROR: POLL_INTERVAL muss eine positive Zahl sein" >&2
    exit 1
fi

echo "Starting Immich Job Daemon..."
echo "Immich URL: $IMMICH_URL"
echo "Poll interval: ${POLL_INTERVAL}s"
echo ""

# Server-Check
echo "Checking Immich server availability..."
if ! curl -s -f -o /dev/null --connect-timeout 10 "$IMMICH_URL/api/server/ping"; then
    echo "ERROR: Kann nicht mit Immich-Server verbinden: $IMMICH_URL" >&2
    exit 1
fi
echo "✓ Server erreichbar"

# API-Key-Check
echo "Verifying API key..."
test_response=$(curl -s -w "%{http_code}" -o /dev/null -X GET "$URL" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json" \
    -H "x-api-key: $API_KEY")

if [ "$test_response" = "401" ] || [ "$test_response" = "403" ]; then
    echo "ERROR: API-Key ungültig oder keine Berechtigungen" >&2
    exit 1
elif [ "$test_response" != "200" ]; then
    echo "WARNING: Unerwarteter HTTP-Code: $test_response" >&2
fi
echo "✓ API-Key erfolgreich geprüft"
echo ""

# Funktionen
fetch_jobs() {
    curl -s -X GET "$URL" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json" \
    -H "x-api-key: $API_KEY" 2>/dev/null
}

set_job() {
    local job="$1"
    local command="$2"
    local payload='{"command":"'"$command"'","force":false}'

    curl -s -X PUT "$URL/$job" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json" \
    -H "x-api-key: $API_KEY" \
    -d "$payload" >/dev/null 2>&1

    if [ $? -ne 0 ]; then
        echo "Fehler beim Setzen von $job auf $command" >&2
    fi
}

# Hauptlogik
manage_jobs() {
    jobs=$(fetch_jobs)
    if [ -z "$jobs" ] || [ "$jobs" = "{}" ]; then
        return
    fi

    smart_active=$(echo "$jobs" | jq -r '.smartSearch.jobCounts.active // 0')
    ocr_active=$(echo "$jobs" | jq -r '.OCR.jobCounts.active // 0')
    ocr_paused=$(echo "$jobs" | jq -r '.OCR.jobCounts.paused // 0')

    # Wenn beide aktiv -> OCR pausieren
    if [ "$smart_active" -gt 0 ] && [ "$ocr_active" -gt 0 ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] ⚠️ smartSearch und OCR laufen gleichzeitig. Pausiere OCR..."
        set_job "OCR" "pause"
    fi

    # Wenn smartSearch inaktiv und OCR pausiert -> OCR wieder starten
    if [ "$smart_active" -eq 0 ] && [ "$ocr_paused" -gt 0 ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] ▶️ smartSearch ist inaktiv. Resumiere OCR..."
        set_job "OCR" "resume"
    fi
}

# Graceful Shutdown
cleanup() {
    echo ""
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 🛑 Shutdown erkannt. Pausiere OCR zur Sicherheit..."
    set_job "OCR" "pause"
    echo "Beende Job-Daemon."
    exit 0
}

trap cleanup TERM INT

# Start Loop
echo "🚀 Job-Daemon gestartet. Drücke Ctrl+C zum Stoppen."
echo ""
while true; do
    manage_jobs
    sleep "$POLL_INTERVAL"
done

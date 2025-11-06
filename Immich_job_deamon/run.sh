#!/bin/sh

# Debug-Ausgabe der Umgebungsvariablen
echo "--- ENVIRONMENT VARIABLES ---"
env | grep -E 'IMMICH_URL|API_KEY|MAX_CONCURRENT_JOBS|POLL_INTERVAL'
echo "-----------------------------"

# Originaler Skriptbeginn
IMMICH_URL="${IMMICH_URL:-http://127.0.0.1:2283}"
API_KEY="${API_KEY:-}"
MAX_CONCURRENT_JOBS="${MAX_CONCURRENT_JOBS:-1}"
POLL_INTERVAL="${POLL_INTERVAL:-10}"
URL="${IMMICH_URL}/api/jobs"

# Rest des Skripts bleibt unverändert...
echo "Starting Immich Job Daemon..."
echo "Immich URL: $IMMICH_URL"
echo "Max concurrent jobs: $MAX_CONCURRENT_JOBS"
echo "Poll interval: ${POLL_INTERVAL}s"

if [ -z "$API_KEY" ]; then
    echo "ERROR: API_KEY environment variable is required" >&2
    exit 1
fi

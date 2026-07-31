#!/bin/sh

# TEMP DEBUG - remove after troubleshooting
echo "=== DEBUG ENV DUMP ===" >&2
env | sort | sed 's/^API_KEY=.*/API_KEY=<redacted, length='"$(printf '%s' "$API_KEY" | wc -c)"'>/' >&2
echo "=== END DEBUG ===" >&2

# Configuration for the API endpoint and headers
# These values should be provided via environment variables
IMMICH_URL="${IMMICH_URL:-http://127.0.0.1:2283}"
API_KEY="${API_KEY:-}"
MAX_CONCURRENT_JOBS="${MAX_CONCURRENT_JOBS:-1}"
POLL_INTERVAL="${POLL_INTERVAL:-10}"
URL="${IMMICH_URL}/api/jobs"

# Only these jobs are managed (heavy ML/RAM-intensive jobs).
# Everything else (sidecar, metadataExtraction, thumbnailGeneration,
# storageTemplateMigration, library, migration, backgroundTask,
# notifications, workflow, backupDatabase, integrityCheck, editor, ...)
# is left completely alone and runs on Immich's own schedule.
HEAVY_JOB_LIST="smartSearch facialRecognition faceDetection duplicateDetection videoConversion ocr"

# Variable to store previous job states
PREV_JOB_STATES=""

# Validate required environment variables
if [ -z "$API_KEY" ]; then
    echo "ERROR: API_KEY environment variable is required" >&2
    exit 1
fi

# Validate MAX_CONCURRENT_JOBS is a positive integer
if ! echo "$MAX_CONCURRENT_JOBS" | grep -qE '^[1-9][0-9]*$'; then
    echo "ERROR: MAX_CONCURRENT_JOBS must be a positive integer" >&2
    exit 1
fi

# Validate POLL_INTERVAL is a positive integer
if ! echo "$POLL_INTERVAL" | grep -qE '^[1-9][0-9]*$'; then
    echo "ERROR: POLL_INTERVAL must be a positive integer" >&2
    exit 1
fi

echo "Starting Immich Job Daemon..."
echo "Immich URL: $IMMICH_URL"
echo "Max concurrent jobs: $MAX_CONCURRENT_JOBS"
echo "Poll interval: ${POLL_INTERVAL}s"
echo "Managed (heavy) jobs: $HEAVY_JOB_LIST"

# Check server availability
echo "Checking Immich server availability..."
if ! curl -s -f -o /dev/null --connect-timeout 10 "$IMMICH_URL/api/server/ping"; then
    echo "ERROR: Cannot connect to Immich server at $IMMICH_URL" >&2
    echo "Please check that:" >&2
    echo "  - IMMICH_URL is correct" >&2
    echo "  - Immich server is running" >&2
    echo "  - Network connection is available" >&2
    exit 1
fi
echo "✓ Successfully connected to Immich server"

# Verify API key by fetching jobs
echo "Verifying API key..."
test_response=$(curl -s -w "%{http_code}" -o /dev/null -X GET "$URL" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json" \
-H "x-api-key: $API_KEY")

if [ "$test_response" = "401" ] || [ "$test_response" = "403" ]; then
    echo "ERROR: API key is invalid or does not have required permissions" >&2
    echo "Please ensure the API key has 'job.read' and 'job.create' permissions" >&2
    exit 1
    elif [ "$test_response" != "200" ]; then
    echo "WARNING: Unexpected response code: $test_response" >&2
fi
echo "✓ API key verified successfully"
echo ""

# Function to fetch the current job statuses from the API
fetch_jobs() {
    curl -s -X GET "$URL" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json" \
    -H "x-api-key: $API_KEY" 2>/dev/null
}

# Function to send a command to pause or resume a specific job via the API
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
        echo "Error setting job $job to $command" >&2
    fi
}

# Resume every managed (heavy) job. Used on shutdown so we never leave a
# job permanently paused if the daemon isn't running.
resume_all_heavy_jobs() {
    for job in $HEAVY_JOB_LIST; do
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] ▶️  Resuming job: $job ($1)"
        set_job "$job" "resume"
    done
}

# Main logic to manage jobs
manage_jobs(

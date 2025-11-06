#!/bin/sh

# Read configuration from Home Assistant options.json
API_KEY=$(jq -r '.API_KEY' /data/options.json)
IMMICH_URL=$(jq -r '.IMMICH_URL' /data/options.json)
MAX_CONCURRENT_JOBS=$(jq -r '.MAX_CONCURRENT_JOBS' /data/options.json)
POLL_INTERVAL=$(jq -r '.POLL_INTERVAL' /data/options.json)

# Validate required environment variables
if [ -z "$API_KEY" ]; then
    echo "ERROR: API_KEY is required" >&2
    exit 1
fi

if ! echo "$MAX_CONCURRENT_JOBS" | grep -qE '^[1-9][0-9]*$'; then
    echo "ERROR: MAX_CONCURRENT_JOBS must be a positive integer" >&2
    exit 1
fi

if ! echo "$POLL_INTERVAL" | grep -qE '^[1-9][0-9]*$'; then
    echo "ERROR: POLL_INTERVAL must be a positive integer" >&2
    exit 1
fi

# Debug output
echo "--- CONFIGURATION ---"
echo "IMMICH_URL=$IMMICH_URL"
echo "API_KEY=$API_KEY"
echo "MAX_CONCURRENT_JOBS=$MAX_CONCURRENT_JOBS"
echo "POLL_INTERVAL=$POLL_INTERVAL"
echo "---------------------"

# Configuration for the API endpoint and headers
URL="$IMMICH_URL/api/jobs"
PREV_JOB_STATES=""

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

# Verify API key
echo "Verifying API key..."
test_response=$(curl -s -w "%{http_code}" -o /dev/null -X GET "$URL"     -H "Content-Type: application/json"     -H "Accept: application/json"     -H "x-api-key: $API_KEY")

if [ "$test_response" = "401" ] || [ "$test_response" = "403" ]; then
    echo "ERROR: API key is invalid or does not have required permissions" >&2
    echo "Please ensure the API key has 'job.read' and 'job.create' permissions" >&2
    exit 1
elif [ "$test_response" != "200" ]; then
    echo "WARNING: Unexpected response code: $test_response" >&2
fi
echo "✓ API key verified successfully"
echo ""

fetch_jobs() {
    curl -s -X GET "$URL"         -H "Content-Type: application/json"         -H "Accept: application/json"         -H "x-api-key: $API_KEY"
}

set_job() {
    local job="$1"
    local command="$2"
    local payload='{"command":"'$command'","force":false}'

    curl -s -X PUT "$URL/$job"         -H "Content-Type: application/json"         -H "Accept: application/json"         -H "x-api-key: $API_KEY"         -d "$payload" >/dev/null 2>&1

    if [ $? -ne 0 ]; then
        echo "Error setting job $job to $command" >&2
    fi
}

manage_jobs() {
    jobs=$(fetch_jobs)

    if [ -z "$jobs" ] || [ "$jobs" = "{}" ]; then
        return
    fi

    priority_job_list="sidecar metadataExtraction storageTemplateMigration thumbnailGeneration smartSearch duplicateDetection faceDetection facialRecognition videoConversion"
    all_jobs=$(echo "$jobs" | jq -r 'keys[]')

    managed_job_list="$priority_job_list"
    for job in $all_jobs; do
        if ! echo " $priority_job_list " | grep -q " $job "; then
            managed_job_list="$managed_job_list $job"
        fi
    done

    has_active_jobs=0
    currently_active_jobs=""

    for job in $managed_job_list; do
        job_counts=$(echo "$jobs" | jq -r ".$job.jobCounts | "\(.active // 0) \(.waiting // 0) \(.paused // 0) \(.delayed // 0)"")

        if [ -z "$job_counts" ]; then
            continue
        fi

        set -- $job_counts
        active=$1

        if [ "$active" -gt 0 ]; then
            has_active_jobs=1
            currently_active_jobs="$currently_active_jobs $job"
        fi
    done

    jobs_to_unpause=""
    jobs_unpaused=0

    if [ "$has_active_jobs" -eq 1 ]; then
        for job in $currently_active_jobs; do
            if [ "$jobs_unpaused" -lt "$MAX_CONCURRENT_JOBS" ]; then
                jobs_to_unpause="$jobs_to_unpause $job"
                jobs_unpaused=$((jobs_unpaused + 1))
            fi
        done
    else
        for job in $managed_job_list; do
            job_counts=$(echo "$jobs" | jq -r ".$job.jobCounts | "\(.active // 0) \(.waiting // 0) \(.paused // 0) \(.delayed // 0)"")

            if [ -z "$job_counts" ]; then
                continue
            fi

            set -- $job_counts
            active=$1
            waiting=$2
            paused=$3
            delayed=$4

            total=$((active + waiting + paused + delayed))

            if [ "$total" -gt 0 ]; then
                if [ "$jobs_unpaused" -lt "$MAX_CONCURRENT_JOBS" ]; then
                    jobs_to_unpause="$jobs_to_unpause $job"
                    jobs_unpaused=$((jobs_unpaused + 1))
                fi
            fi
        done
    fi

    new_job_states=""

    for job in $managed_job_list; do
        if echo " $jobs_to_unpause " | grep -q " $job "; then
            new_state="resume"
        else
            new_state="pause"
        fi

        new_job_states="${new_job_states}${job}:${new_state},"

        if ! echo "$PREV_JOB_STATES" | grep -q "${job}:${new_state}"; then
            if [ "$new_state" = "resume" ]; then
                echo "[$(date '+%Y-%m-%d %H:%M:%S')] ▶️  Resuming job: $job"
            else
                echo "[$(date '+%Y-%m-%d %H:%M:%S')] ⏸️  Pausing job: $job"
            fi
            set_job "$job" "$new_state"
        fi
    done

    PREV_JOB_STATES="$new_job_states"
}

cleanup() {
    echo ""
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 🛑 Received shutdown signal, exiting gracefully..."
    exit 0
}

trap cleanup TERM INT

echo "🚀 Job daemon started. Press Ctrl+C to stop."
echo ""
while true; do
    manage_jobs
    sleep "$POLL_INTERVAL"
done

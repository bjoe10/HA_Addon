#!/bin/sh

OPTIONS_FILE="/data/options.json"

# Read options from Supervisor's options.json (the reliable mechanism),
# but still allow env vars to override for local/manual testing.
if [ -f "$OPTIONS_FILE" ]; then
    IMMICH_URL="${IMMICH_URL:-$(jq -r '.IMMICH_URL // empty' "$OPTIONS_FILE")}"
    API_KEY="${API_KEY:-$(jq -r '.API_KEY // empty' "$OPTIONS_FILE")}"
    MAX_CONCURRENT_JOBS="${MAX_CONCURRENT_JOBS:-$(jq -r '.MAX_CONCURRENT_JOBS // empty' "$OPTIONS_FILE")}"
    POLL_INTERVAL="${POLL_INTERVAL:-$(jq -r '.POLL_INTERVAL // empty' "$OPTIONS_FILE")}"
fi

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

# Wait for the server instead of exiting, so the daemon survives Immich
# starting later than this add-on (e.g. after a host reboot).
echo "Checking Immich server availability..."
until curl -s -f -o /dev/null --connect-timeout 10 --max-time 15 "$IMMICH_URL/api/server/ping"; do
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Immich server at $IMMICH_URL not reachable yet, retrying in ${POLL_INTERVAL}s..." >&2
    sleep "$POLL_INTERVAL"
done
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

# Set while Immich is unreachable, so the outage is logged only once
IMMICH_DOWN=0

# Function to fetch the current job statuses from the API.
# Prints nothing if the server is down or answers with an error / non-JSON.
fetch_jobs() {
    local response
    response=$(curl -s -f --connect-timeout 10 --max-time 30 -X GET "$URL" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json" \
    -H "x-api-key: $API_KEY" 2>/dev/null) || return 1

    echo "$response" | jq -e 'type == "object"' >/dev/null 2>&1 || return 1
    echo "$response"
}

# Function to send a command to pause or resume a specific job via the API
set_job() {
    local job="$1"
    local command="$2"
    local payload='{"command":"'"$command"'","force":false}'

    if ! curl -s -f --connect-timeout 10 --max-time 30 -X PUT "$URL/$job" \
        -H "Content-Type: application/json" \
        -H "Accept: application/json" \
        -H "x-api-key: $API_KEY" \
        -d "$payload" >/dev/null 2>&1; then
        echo "Error setting job $job to $command" >&2
        return 1
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
manage_jobs() {
    # Fetch all jobs from the API
    if ! jobs=$(fetch_jobs); then
        if [ "$IMMICH_DOWN" -eq 0 ]; then
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] ⚠️  Immich not reachable, waiting for it to come back..." >&2
            IMMICH_DOWN=1
        fi
        # Immich may come back with different pause states (e.g. after a
        # restart), so forget what we sent and re-apply everything later.
        PREV_JOB_STATES=""
        return
    fi

    if [ "$IMMICH_DOWN" -eq 1 ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✓ Immich reachable again, re-applying job states"
        IMMICH_DOWN=0
    fi

    if [ "$jobs" = "{}" ]; then
        return
    fi

    # Only ever look at / touch the fixed heavy-job list, in priority order.
    managed_job_list="$HEAVY_JOB_LIST"

    # Check if any managed jobs are currently actively running (active > 0)
    # If yes, don't interrupt them - let them finish
    has_active_jobs=0
    currently_active_jobs=""

    for job in $managed_job_list; do
        job_counts=$(echo "$jobs" | jq -r ".$job.jobCounts | \"\(.active // 0) \(.waiting // 0) \(.paused // 0) \(.delayed // 0)\"" 2>/dev/null)

        if [ -z "$job_counts" ]; then
            continue
        fi

        set -- $job_counts
        active=$1

        # If this job has active tasks, don't interrupt it
        if [ "$active" -gt 0 ]; then
            has_active_jobs=1
            currently_active_jobs="$currently_active_jobs $job"
        fi
    done

    # Collect jobs with activity and unpause the first N jobs based on MAX_CONCURRENT_JOBS
    jobs_to_unpause=""
    jobs_unpaused=0

    # If there are active jobs, keep them running and don't start new ones
    if [ "$has_active_jobs" -eq 1 ]; then
        # Keep currently active jobs running
        for job in $currently_active_jobs; do
            if [ "$jobs_unpaused" -lt "$MAX_CONCURRENT_JOBS" ]; then
                jobs_to_unpause="$jobs_to_unpause $job"
                jobs_unpaused=$((jobs_unpaused + 1))
            fi
        done
    else
        # No active jobs - select new jobs by priority (within the heavy list only)
        for job in $managed_job_list; do
            job_counts=$(echo "$jobs" | jq -r ".$job.jobCounts | \"\(.active // 0) \(.waiting // 0) \(.paused // 0) \(.delayed // 0)\"" 2>/dev/null)

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

    # Unpause selected heavy jobs, pause all other heavy jobs.
    # Non-heavy jobs (sidecar, metadataExtraction, thumbnailGeneration, ...)
    # are never referenced here at all, so Immich runs them unmanaged.
    for job in $managed_job_list; do
        if echo " $jobs_to_unpause " | grep -q " $job "; then
            new_state="resume"
        else
            new_state="pause"
        fi

        # Prefer the queue's real pause state as reported by Immich, so a
        # restarted Immich that reset its queues gets corrected right away.
        # Fall back to our own memory if the API doesn't report it.
        is_paused=$(echo "$jobs" | jq -r ".$job.queueStatus.isPaused | if . == null then empty else tostring end" 2>/dev/null)
        needs_update=0
        if [ "$is_paused" = "true" ] || [ "$is_paused" = "false" ]; then
            if [ "$new_state" = "pause" ] && [ "$is_paused" = "false" ]; then
                needs_update=1
            elif [ "$new_state" = "resume" ] && [ "$is_paused" = "true" ]; then
                needs_update=1
            fi
        elif ! echo "$PREV_JOB_STATES" | grep -q "${job}:${new_state}"; then
            needs_update=1
        fi

        if [ "$needs_update" -eq 1 ]; then
            if [ "$new_state" = "resume" ]; then
                echo "[$(date '+%Y-%m-%d %H:%M:%S')] ▶️  Resuming job: $job"
            else
                echo "[$(date '+%Y-%m-%d %H:%M:%S')] ⏸️  Pausing job: $job"
            fi
            # Only remember the state if the command went through,
            # otherwise it is retried on the next poll.
            set_job "$job" "$new_state" || continue
        fi

        new_job_states="${new_job_states}${job}:${new_state},"
    done

    PREV_JOB_STATES="$new_job_states"
}

# Graceful shutdown handler - always leave the heavy jobs unpaused so a
# stopped/restarted daemon never permanently blocks processing.
cleanup() {
    echo ""
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 🛑 Received shutdown signal, resuming heavy jobs before exit..."
    resume_all_heavy_jobs "shutdown cleanup"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 🛑 Exiting gracefully..."
    exit 0
}

# Trap SIGTERM and SIGINT for graceful shutdown
trap cleanup TERM INT

# Run the job manager loop
echo "🚀 Job daemon started. Press Ctrl+C to stop."
echo ""
while true; do
    manage_jobs
    sleep "$POLL_INTERVAL"
done

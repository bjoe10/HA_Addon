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

# The rest of the original script would follow here...

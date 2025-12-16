#!/usr/bin/env bashio

# ==============================================================================
# CONFIGURATION
# ==============================================================================

bashio::log.info "Loading configuration..."

# Required configuration
DEFAULT_DOMAIN=$(bashio::config 'default_domain')
IS_HTTPS_ENABLED=$(bashio::config 'is_https_enabled')
GEOLITE_LICENSE_KEY=$(bashio::config 'geolite_license_key')

# Database configuration
DB_DRIVER=$(bashio::config 'db_driver')
DB_NAME=$(bashio::config 'db_name')
DB_USER=$(bashio::config 'db_user')
DB_PASSWORD=$(bashio::config 'db_password')
DB_HOST=$(bashio::config 'db_host')
DB_PORT=$(bashio::config 'db_port')

# Optional configuration
REDIS_SERVERS=$(bashio::config 'redis_servers')
INITIAL_API_KEY=$(bashio::config 'initial_api_key')

# ==============================================================================
# PREPARATION
# ==============================================================================

# Ensure data directory exists
mkdir -p /data

# Clean up any existing container
bashio::log.info "Cleaning up existing containers..."
docker stop shlink 2>/dev/null || true
docker rm shlink 2>/dev/null || true

# ==============================================================================
# BUILD DOCKER COMMAND
# ==============================================================================

bashio::log.info "Building Docker command..."

# Base command
CMD="docker run -d \
    --name shlink \
    --restart unless-stopped \
    -p 8080:8080 \
    -v /data:/data"

# Add environment variables
CMD="${CMD} -e DEFAULT_DOMAIN=${DEFAULT_DOMAIN}"
CMD="${CMD} -e IS_HTTPS_ENABLED=${IS_HTTPS_ENABLED}"

# Add GeoLite license key if provided
if [[ -n "${GEOLITE_LICENSE_KEY}" ]]; then
    CMD="${CMD} -e GEOLITE_LICENSE_KEY=${GEOLITE_LICENSE_KEY}"
fi

# Database configuration
if [[ "${DB_DRIVER}" != "sqlite" ]]; then
    CMD="${CMD} -e DB_DRIVER=${DB_DRIVER}"
    CMD="${CMD} -e DB_NAME=${DB_NAME}"
    CMD="${CMD} -e DB_USER=${DB_USER}"
    CMD="${CMD} -e DB_PASSWORD=${DB_PASSWORD}"
    CMD="${CMD} -e DB_HOST=${DB_HOST}"
    
    if [[ -n "${DB_PORT}" ]]; then
        CMD="${CMD} -e DB_PORT=${DB_PORT}"
    fi
fi

# Redis configuration
if [[ -n "${REDIS_SERVERS}" ]]; then
    CMD="${CMD} -e REDIS_SERVERS=${REDIS_SERVERS}"
fi

# Initial API key
if [[ -n "${INITIAL_API_KEY}" ]]; then
    CMD="${CMD} -e INITIAL_API_KEY=${INITIAL_API_KEY}"
fi

# Add image
CMD="${CMD} shlinkio/shlink:stable"

bashio::log.info "Command: ${CMD}"

# ==============================================================================
# START CONTAINER
# ==============================================================================

bashio::log.info "Starting Shlink container..."
eval "${CMD}"

# Wait for container to start
sleep 5

# ==============================================================================
# API KEY EXTRACTION
# ==============================================================================

extract_api_key() {
    local max_attempts=20
    local attempt=1
    
    bashio::log.info "Attempting to extract API key from logs..."
    
    while [[ ${attempt} -le ${max_attempts} ]]; do
        bashio::log.info "Attempt ${attempt}/${max_attempts}"
        
        # Check if initial API key was provided
        if [[ -n "${INITIAL_API_KEY}" ]]; then
            bashio::log.info "✅ Using provided API key"
            echo "API Key: ${INITIAL_API_KEY}" > /data/api_key.txt
            echo "Source: Provided in configuration" >> /data/api_key.txt
            return 0
        fi
        
        # Get logs from container
        local logs
        logs=$(docker logs shlink 2>&1 || true)
        
        # Look for API key in logs
        if echo "${logs}" | grep -q "apiKey_"; then
            local api_key
            api_key=$(echo "${logs}" | grep -o "apiKey_[a-zA-Z0-9]*" | head -1)
            
            if [[ -n "${api_key}" ]]; then
                bashio::log.info "✅ API key found in logs!"
                echo "API Key: ${api_key}" > /data/api_key.txt
                echo "Source: Extracted from logs" >> /data/api_key.txt
                echo "Extracted at: $(date)" >> /data/api_key.txt
                return 0
            fi
        fi
        
        # Try to generate API key via CLI
        if [[ ${attempt} -eq 5 ]] || [[ ${attempt} -eq 10 ]]; then
            bashio::log.info "Trying to generate API key via CLI..."
            docker exec shlink shlink api-key:generate 2>/dev/null || true
        fi
        
        attempt=$((attempt + 1))
        sleep 10
    done
    
    bashio::log.warning "⚠️ Could not extract API key automatically"
    echo "No API key could be automatically extracted." > /data/api_key.txt
    echo "You can generate one manually by running:" >> /data/api_key.txt
    echo "docker exec shlink shlink api-key:generate" >> /data/api_key.txt
    return 1
}

# Extract API key
extract_api_key

# ==============================================================================
# MONITORING
# ==============================================================================

bashio::log.info "=========================================="
bashio::log.info "Shlink is now running!"
bashio::log.info "Web Interface: http://[HASS_IP]:8080"
bashio::log.info "API Documentation: http://[HASS_IP]:8080/api-specs"
bashio::log.info "API key stored in: /data/api_key.txt"
bashio::log.info "=========================================="

# Display API key if found
if [[ -f /data/api_key.txt ]]; then
    bashio::log.info "API Key Information:"
    cat /data/api_key.txt | while read line; do
        bashio::log.info "  ${line}"
    done
fi

# Monitor container indefinitely
bashio::log.info "Starting container monitor..."
while true; do
    if ! docker ps --filter "name=shlink" --format "{{.Names}}" | grep -q "shlink"; then
        bashio::log.error "❌ Shlink container stopped!"
        bashio::log.error "Attempting to restart..."
        docker start shlink || {
            bashio::log.error "Failed to restart container. Exiting."
            exit 1
        }
    fi
    
    # Check container health every 30 seconds
    sleep 30
done

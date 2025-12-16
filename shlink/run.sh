#!/usr/bin/env bashio

# Load configuration values
declare DEFAULT_DOMAIN
declare IS_HTTPS_ENABLED
declare GEOLITE_LICENSE_KEY
declare DB_DRIVER
declare DB_NAME
declare DB_USER
declare DB_PASSWORD
declare DB_HOST
declare DB_PORT
declare REDIS_SERVERS
declare INITIAL_API_KEY

DEFAULT_DOMAIN=$(bashio::config 'default_domain')
IS_HTTPS_ENABLED=$(bashio::config 'is_https_enabled')
GEOLITE_LICENSE_KEY=$(bashio::config 'geolite_license_key')
DB_DRIVER=$(bashio::config 'db_driver')
DB_NAME=$(bashio::config 'db_name')
DB_USER=$(bashio::config 'db_user')
DB_PASSWORD=$(bashio::config 'db_password')
DB_HOST=$(bashio::config 'db_host')
DB_PORT=$(bashio::config 'db_port')
REDIS_SERVERS=$(bashio::config 'redis_servers')
INITIAL_API_KEY=$(bashio::config 'initial_api_key')

# Build environment variables for Docker
ENV_ARGS=""

# Required variables
ENV_ARGS="${ENV_ARGS} -e DEFAULT_DOMAIN=${DEFAULT_DOMAIN}"
ENV_ARGS="${ENV_ARGS} -e IS_HTTPS_ENABLED=${IS_HTTPS_ENABLED}"

# Optional variables
if [ -n "${GEOLITE_LICENSE_KEY}" ]; then
    ENV_ARGS="${ENV_ARGS} -e GEOLITE_LICENSE_KEY=${GEOLITE_LICENSE_KEY}"
fi

# Database configuration
if [ "${DB_DRIVER}" != "sqlite" ]; then
    ENV_ARGS="${ENV_ARGS} -e DB_DRIVER=${DB_DRIVER}"
    ENV_ARGS="${ENV_ARGS} -e DB_NAME=${DB_NAME}"
    ENV_ARGS="${ENV_ARGS} -e DB_USER=${DB_USER}"
    ENV_ARGS="${ENV_ARGS} -e DB_PASSWORD=${DB_PASSWORD}"
    ENV_ARGS="${ENV_ARGS} -e DB_HOST=${DB_HOST}"
    
    if [ -n "${DB_PORT}" ]; then
        ENV_ARGS="${ENV_ARGS} -e DB_PORT=${DB_PORT}"
    fi
fi

# Redis configuration
if [ -n "${REDIS_SERVERS}" ]; then
    ENV_ARGS="${ENV_ARGS} -e REDIS_SERVERS=${REDIS_SERVERS}"
fi

# Initial API key (optional - if not provided, will be generated)
if [ -n "${INITIAL_API_KEY}" ]; then
    ENV_ARGS="${ENV_ARGS} -e INITIAL_API_KEY=${INITIAL_API_KEY}"
fi

# Volume mapping
VOLUME_ARGS="-v /data:/data"

bashio::log.info "Starting Shlink container..."
bashio::log.info "Domain: ${DEFAULT_DOMAIN}"
bashio::log.info "HTTPS: ${IS_HTTPS_ENABLED}"
bashio::log.info "Database driver: ${DB_DRIVER}"

# Start Shlink container
CONTAINER_ID=$(docker run -d \
    --name shlink \
    ${ENV_ARGS} \
    ${VOLUME_ARGS} \
    -p 8080:8080 \
    shlinkio/shlink:stable)

bashio::log.info "Shlink container started with ID: ${CONTAINER_ID}"

# Function to extract API key from logs
extract_api_key() {
    bashio::log.info "Checking for API key generation..."
    
    # Wait a bit for container to initialize
    sleep 10
    
    # Check if initial API key was provided
    if [ -n "${INITIAL_API_KEY}" ]; then
        bashio::log.info "Using provided API key: ${INITIAL_API_KEY}"
        echo "API Key: ${INITIAL_API_KEY}" > /data/api_key.txt
        return 0
    fi
    
    # Try to extract API key from logs
    for i in {1..10}; do
        bashio::log.info "Attempt ${i}/10 to extract API key from logs..."
        
        # Get recent logs
        LOGS=$(docker logs --tail 100 "${CONTAINER_ID}" 2>/dev/null || true)
        
        # Look for API key in logs (Shlink typically shows it when generated)
        API_KEY=$(echo "${LOGS}" | grep -oE "apiKey_[a-zA-Z0-9]+" | head -1)
        
        if [ -n "${API_KEY}" ]; then
            bashio::log.info "✅ API Key found in logs!"
            bashio::log.info "API Key: ${API_KEY}"
            echo "API Key: ${API_KEY}" > /data/api_key.txt
            return 0
        fi
        
        # Alternative: try to generate API key via CLI
        if [ ${i} -eq 3 ]; then
            bashio::log.info "Trying to generate API key via CLI..."
            docker exec "${CONTAINER_ID}" shlink api-key:generate 2>/dev/null || true
        fi
        
        sleep 5
    done
    
    bashio::log.warning "Could not automatically extract API key from logs"
    bashio::log.warning "You can manually generate it by running:"
    bashio::log.warning "docker exec ${CONTAINER_ID} shlink api-key:generate"
    return 1
}

# Try to extract API key
extract_api_key || true

# Monitor container
bashio::log.info "Shlink is running on port 8080"
bashio::log.info "Web interface: http://[HASS_IP]:8080"
bashio::log.info "Check /data/api_key.txt for your API key if it was generated"

# Keep script running
while true; do
    if ! docker ps --filter "name=shlink" --format "{{.Names}}" | grep -q "shlink"; then
        bashio::log.error "Shlink container stopped unexpectedly"
        exit 1
    fi
    sleep 30
done

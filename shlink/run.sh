#!/usr/bin/with-contenv bashio

bashio::log.info "Starting Shlink URL Shortener..."

# Read configuration
DEFAULT_DOMAIN=$(bashio::config 'default_domain')
IS_HTTPS_ENABLED=$(bashio::config 'is_https_enabled')
GEOLITE_LICENSE_KEY=$(bashio::config 'geolite_license_key')
INITIAL_API_KEY=$(bashio::config 'initial_api_key')
DB_DRIVER=$(bashio::config 'db_driver')
DB_NAME=$(bashio::config 'db_name')
DB_USER=$(bashio::config 'db_user')
DB_PASSWORD=$(bashio::config 'db_password')
DB_HOST=$(bashio::config 'db_host')
DB_PORT=$(bashio::config 'db_port')
REDIS_SERVERS=$(bashio::config 'redis_servers')
TIMEZONE=$(bashio::config 'timezone')

# Export mandatory environment variables
export DEFAULT_DOMAIN="${DEFAULT_DOMAIN}"
export IS_HTTPS_ENABLED="${IS_HTTPS_ENABLED}"
export TZ="${TIMEZONE}"

# Export GeoLite2 license key if provided
if bashio::config.has_value 'geolite_license_key'; then
    export GEOLITE_LICENSE_KEY="${GEOLITE_LICENSE_KEY}"
    bashio::log.info "GeoLite2 license key configured"
fi

# Export initial API key if provided
if bashio::config.has_value 'initial_api_key' && [ -n "${INITIAL_API_KEY}" ]; then
    export INITIAL_API_KEY="${INITIAL_API_KEY}"
    bashio::log.info "Initial API key configured"
    bashio::log.warning "============================================="
    bashio::log.warning "API Key: ${INITIAL_API_KEY}"
    bashio::log.warning "============================================="
fi

# Configure database if not using SQLite
if [ "${DB_DRIVER}" != "sqlite" ]; then
    export DB_DRIVER="${DB_DRIVER}"
    export DB_NAME="${DB_NAME}"
    
    if bashio::config.has_value 'db_user'; then
        export DB_USER="${DB_USER}"
    fi
    
    if bashio::config.has_value 'db_password'; then
        export DB_PASSWORD="${DB_PASSWORD}"
    fi
    
    if bashio::config.has_value 'db_host'; then
        export DB_HOST="${DB_HOST}"
    fi
    
    if bashio::config.has_value 'db_port'; then
        export DB_PORT="${DB_PORT}"
    fi
    
    bashio::log.info "Using external database: ${DB_DRIVER}"
else
    bashio::log.info "Using SQLite database"
fi

# Configure Redis if provided
if bashio::config.has_value 'redis_servers' && [ -n "${REDIS_SERVERS}" ]; then
    export REDIS_SERVERS="${REDIS_SERVERS}"
    bashio::log.info "Redis servers configured: ${REDIS_SERVERS}"
fi

bashio::log.info "Default domain: ${DEFAULT_DOMAIN}"
bashio::log.info "HTTPS enabled: ${IS_HTTPS_ENABLED}"
bashio::log.info "Timezone: ${TIMEZONE}"

# Start Shlink
bashio::log.info "Starting Shlink server on port 8080..."

# Execute the original entrypoint from Shlink image
exec /usr/local/bin/docker-entrypoint.sh

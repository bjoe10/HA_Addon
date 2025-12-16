
# HA_Addon/shlink/Dockerfile
ARG BUILD_VERSION
ARG BUILD_ARCH

FROM shlinkio/shlink:stable

# Labels für Home Assistant Supervisor
LABEL io.hass.version="${BUILD_VERSION}" \
      io.hass.type="addon" \
      io.hass.arch="${BUILD_ARCH}"

# Hilfstools (Optionen lesen)
RUN if command -v apk >/dev/null 2>&1; then \
      apk add --no-cache bash jq; \
    elif command -v apt-get >/dev/null 2>&1; then \
      apt-get update && apt-get install -y --no-install-recommends bash jq && \
      rm -rf /var/lib/apt/lists/*; \
    else \
      echo "Kein unterstützter Paketmanager gefunden." && exit 1; \
    fi

# Startskript
COPY run.sh /run.sh
RUN chmod +x /run.sh

## Shlink-API-Port
EXPOSE 8080

# Start: Optionen -> ENV -> Upstream Entrypoint

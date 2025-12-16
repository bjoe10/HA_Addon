ARG BUILD_FROM=ghcr.io/home-assistant/addon-base/amd64:latest
FROM ${BUILD_FROM}

# Install Docker client
RUN apk add --no-cache docker

# Labels
LABEL \
    io.hass.name="Shlink" \
    io.hass.description="Self-hosted URL shortener" \
    io.hass.type="addon" \
    io.hass.version="4.0.1"

# Copy run script
COPY run.sh /
RUN chmod a+x /run.sh

# Set working directory
WORKDIR /data

CMD [ "/run.sh" ]

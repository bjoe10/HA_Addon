ARG BUILD_FROM
FROM ${BUILD_FROM}

# Labels
LABEL \
    io.hass.name="Shlink" \
    io.hass.description="Self-hosted URL shortener" \
    io.hass.type="addon" \
    io.hass.version="4.0.1"

# Install dependencies
RUN apk add --no-cache \
    bash \
    curl \
    jq

# Copy run script
COPY run.sh /
RUN chmod a+x /run.sh

# Set working directory
WORKDIR /data

# Run as non-root user
USER 1000:1000

CMD [ "/run.sh" ]

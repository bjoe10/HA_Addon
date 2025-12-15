ARG BUILD_FROM
FROM $BUILD_FROM

# Set environment
ENV LANG C.UTF-8

# Use official Shlink Web Client image
LABEL "io.hass.version"="1.0"
LABEL "io.hass.type"="addon"

# Tell HA Supervisor which architecture is supported
ARG BUILD_ARCH

# Pull the Web Client image
RUN apk add --no-cache bash curl

# Equivalent of `docker run shlinkio/shlink-web-client`
CMD ["sh", "-c", "exec /usr/bin/docker run --rm -p 8080:8080 shlinkio/shlink-web-client"]

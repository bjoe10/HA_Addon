
# Home Assistant add-on: Shlink URL Shortener
# Wir nutzen das offizielle Shlink-Image und legen nur einen dünnen Wrapper darüber
FROM shlinkio/shlink:stable

# Tools (bash, jq, tzdata, uuidgen) installieren – funktioniert auf Alpine & Debian
RUN set -eux; \
    if [ -f /etc/alpine-release ]; then \
      apk add --no-cache bash jq tzdata util-linux ca-certificates; \
    else \
      export DEBIAN_FRONTEND=noninteractive; \
      apt-get update; \
      apt-get install -y --no-install-recommends bash jq tzdata uuid-runtime ca-certificates; \
      rm -rf /var/lib/apt/lists/*; \
    fi

# Entryscript
COPY run.sh /run.sh
RUN chmod +x /run.sh

# Labels für HA (falls nicht über HA-Buildsystem gebaut)
ARG BUILD_VERSION="0.1.0"
ARG BUILD_ARCH="amd64|aarch64|armv7|i386"
LABEL \
  io.hass.version="${BUILD_VERSION}" \
  io.hass.type="addon" \
  io.hass.arch="${BUILD_ARCH}"

# Shlink API-Port
EXPOSE 8080

# Unser Wrapper startet und übergibt dann an das Original-Entrypoint
ENTRY

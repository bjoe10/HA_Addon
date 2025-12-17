
# Home Assistant Add-on: Shlink URL Shortener (Server & REST-API)
# Wir nutzen das offizielle Shlink-Image und legen unseren HA-Wrapper darüber.
FROM shlinkio/shlink:stable

# Nützliche Tools (bash, jq, tzdata, uuidgen) für HA-Umgebung
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

# HA-Labels (falls nicht über das HA-Buildsystem gebaut)
ARG BUILD_VERSION="0.1.0"
ARG BUILD_ARCH="amd64|aarch64|armv7|i386"
LABEL \
  io.hass.version="${BUILD_VERSION}" \
  io.hass.type="addon" \
  io.hass.arch="${BUILD_ARCH}"

# Shlink API-Port
EXPOSE 8080

# Wrapper startet und übergibt an Shlink-Entrypoint
ENTRYPOINT ["/run.sh"]
``


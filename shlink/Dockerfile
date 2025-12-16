
# Add-on Build-Labels (werden vom HA-Builder gesetzt, wenn vorhanden)
ARG BUILD_VERSION
ARG BUILD_ARCH

# ==> Offizielles Shlink-Image als Basis
FROM shlinkio/shlink:stable

# Hilfstools für das Add-on
RUN apk add --no-cache jq tzdata

# Unser Entrypoint-Wrapper
COPY run.sh /usr/local/bin/ha-run.sh
RUN chmod +x /usr/local/bin/ha-run.sh

# HA-Add-on Labels (wichtig bei eigenem Base-Image)
LABEL \
  io.hass.version="${BUILD_VERSION}" \
  io.hass.type="addon" \
  io.hass.arch="${BUILD_ARCH}"

# Starte unseren Wrapper; der ruft am Ende den originalen Shlink-Entrypoint auf
ENTRYPOINT ["/bin/sh", "/usr/local/bin/ha-run.sh"]


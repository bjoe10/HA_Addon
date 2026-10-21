FROM lejianwen/rustdesk-server-s6:v0.1.2

ARG BUILD_ARCH
ARG BUILD_VERSION

LABEL \
  io.hass.type="app" \
  io.hass.version="${BUILD_VERSION}" \
  io.hass.arch="${BUILD_ARCH}"

RUN apk add --no-cache jq

COPY run.sh /run-rustdesk.sh
RUN chmod 0755 /run-rustdesk.sh

# The upstream image uses s6-overlay as PID 1. The wrapper reads Supervisor
# options, sets the upstream environment, then hands control back to s6.
ENTRYPOINT ["/run-rustdesk.sh"]

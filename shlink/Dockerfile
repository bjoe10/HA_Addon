
# Home Assistant Add-on Base verwenden
ARG BUILD_FROM
FROM $BUILD_FROM

# (Optional) Zusätzliche Tools
RUN apk add --no-cache php php-cli php-json

# Dein Startskript
COPY --chmod=0755 run.sh /run.sh

# s6-overlay erwartet CMD auf dein Skript
CMD ["/run.sh"



# Home Assistant Add-on Base-Image verwenden (s6-overlay integriert)
ARG BUILD_FROM
FROM $BUILD_FROM

# Optional: Minimale Tools; php-cli wird für das leichte JSON-Parsing genutzt
RUN apk add --no-cache php-cli

# Startskript kopieren, ausführbar machen und Windows-CRLF -> LF sicherstellen
COPY --chmod=0755 run.sh /run.sh
RUN sed -i 's/\r$//' /run.sh

# Add-on startet sein Skript via CMD (kein# Add-on startet sein Skript via CMD (kein eigener ENTRYPOINT!)


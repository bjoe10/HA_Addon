
# Dockerfile
# Home Assistant Base-Image verwenden
ARG BUILD_FROM
FROM $BUILD_FROM

# Optional: Tools, falls du sie brauchst
RUN apk add --no-cache php-cli

# Startskript kopieren, Ausführbarkeit & Windows-CRLF -> LF sicherstellen
COPY --chmod=0755 run.sh /run.sh
RUN sed -i 's/\r$//' /run.sh

# s6-overlay erwartet ein CMD (kein eigener ENTRYPOINT)
CMD [


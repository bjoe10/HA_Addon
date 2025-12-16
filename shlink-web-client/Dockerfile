
# Nutze das offizielle Shlink Web Client Image (liefert statische App über nginx:alpine). [1](https://hub.docker.com/r/shlinkio/shlink-web-client/)
FROM shlinkio/shlink-web-client:latest

# Hilfstools für das Startskript
RUN apk add --no-cache bash jq

# Add-on Startskript einspielen
COPY run.sh /run.sh
RUN chmod +x /run.sh

## Container startet unser Skript, das servers.json erzeugt und nginx im Vordergrund startet


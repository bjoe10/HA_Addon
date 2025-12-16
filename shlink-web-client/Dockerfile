
# Offizielles Shlink Web Client Image (nginx:alpine + App)
FROM shlinkio/shlink-web-client:latest

# Für Paketinstallation Root-Rechte verwenden
USER root

# Hilfstools fürs Startskript
RUN apk add --no-cache bash jq

# Startskript einspielen
COPY run.sh /run.sh
RUN chmod +x /run.sh

EXPOSE 8080

## Unser Skript erzeugt servers.json und startet nginx im Vordergrund


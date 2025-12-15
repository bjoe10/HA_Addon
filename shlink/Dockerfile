# Nutze das offizielle, stabile Shlink Docker-Image als Basis
FROM shlinkio/shlink:stable

# Wir wechseln zu Root, um Pakete zu installieren
USER root

# Installiere jq (notwendig um die options.json von HA zu parsen)
RUN apk add --no-cache jq

# Kopiere das Startskript und setze Ausführungsrechte
COPY run.sh /run.sh
RUN chmod a+x /run.sh

# Environment Variablen für die SQLite-Datenbank im persistenten Speicher (/data)
# Dies ist die Standardeinstellung und muss nicht mehr vom Nutzer geändert werden
ENV DB_DRIVER=sqlite
ENV DB_NAME=/data/shlink_db.sqlite

# Der Startbefehl ruft unser Skript auf
CMD [ "/run.sh" ]

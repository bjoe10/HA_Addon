ARG BUILD_FROM
# Wir nutzen das offizielle Image als Basis, nicht das HA-Base-Image, 
# da Shlink komplexe PHP-Abhängigkeiten hat.
FROM shlinkio/shlink:stable

# Wir wechseln zu Root, um Pakete zu installieren und Rechte zu setzen
USER root

# Installiere jq (notwendig um options.json von HA zu parsen)
RUN apk add --no-cache jq

# Kopiere das Startskript
COPY run.sh /run.sh
RUN chmod a+x /run.sh

# Environment Variablen für Persistenz (Wichtig!)
# Wir legen die Datenbank in /data, damit sie bei Updates nicht gelöscht wird.
ENV DB_DRIVER=sqlite
ENV DB_NAME=/data/shlink_db.sqlite

# Startbefehl
CMD [ "/run.sh" ]

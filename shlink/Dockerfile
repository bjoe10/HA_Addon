# WIR NUTZEN JETZT DAS STABILE SLIM IMAGE (RoadRunner-basiert)
FROM shlinkio/shlink:slim

# Wir wechseln zu root, um Pakete zu installieren und Rechte zu setzen
USER root

# jq wird benötigt, um die options.json von Home Assistant zu parsen
RUN apk add --no-cache jq bash

# Kopiere das Start-Skript
COPY run.sh /run.sh
RUN chmod +x /run.sh

# Das Slim-Image verwendet einen bekannten Entrypoint, den wir für unseren Start beibehalten.
ENTRYPOINT ["/run.sh"]

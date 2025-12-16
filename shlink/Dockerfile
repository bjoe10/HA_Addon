# Wir nutzen das offizielle Stable Image als Basis
FROM shlinkio/shlink:stable

# Wir wechseln zu root, um Pakete zu installieren und Rechte zu setzen
USER root

# jq wird benötigt, um die options.json von Home Assistant zu parsen
RUN apk add --no-cache jq bash

# Kopiere das Start-Skript
COPY run.sh /run.sh
RUN chmod +x /run.sh

# Das offizielle Image hat einen Entrypoint. Wir überschreiben ihn,
# damit unser Skript zuerst läuft.
ENTRYPOINT ["/run.sh"]

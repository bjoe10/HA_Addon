# Nutze das offizielle Shlink Web Client Image
FROM shlinkio/shlink-web-client:latest

# Wir wechseln zu Root, um das Startskript hinzuzufügen
USER root

# Installiere jq
RUN apk add --no-cache jq

# Kopiere das Startskript
COPY run.sh /run.sh
RUN chmod a+x /run.sh

# Da das Image Nginx nutzt, müssen wir es über das Skript starten
CMD [ "/run.sh" ]

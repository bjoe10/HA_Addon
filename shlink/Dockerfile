
ARG SHLINK_TAG=stable
FROM shlinkio/shlink:${SHLINK_TAG}

# Als root starten: /data ist dann beschreibbar
USER 0

# Skript mit Ausführungsrechten kopieren
COPY --chmod=0755 run.sh /run.sh

# Robuster Start: Shell führt das Skript aus (vermeidet „exec format error“)
ENTRYPOINT ["/bin/sh","/run.sh"]



ARG SHLINK_TAG=stable
FROM shlinkio/shlink:${SHLINK_TAG}

# Als root starten: /data ist dann beschreibbar (HA Add-on Persistenz)
USER 0

## Skript mit Ausführungsrechten direkt in die Schicht kopieren
COPY --chmod=0755 run.sh /run.sh

# Robuster Start: Shell führt das Skript aus


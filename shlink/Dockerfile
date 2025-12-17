
ARG SHLINK_TAG=stable
FROM shlinkio/shlink:${SHLINK_TAG}

# Als root starten: /data (Add-on-Persistenz) ist dann beschreibbar
USER 0

# Skript mit Ausführungsrechten direkt in die Schicht kopieren
COPY --chmod=0755 run.sh /run.sh

# Robuster Entrypoint: Shell startet das Skript (vermeidet Shebang/BOM/CRLF-Probleme)
ENTRY


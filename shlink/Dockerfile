
ARG SHLINK_TAG=stable
FROM shlinkio/shlink:${SHLINK_TAG}

# Startskript direkt mit Ausführungsrechten kopieren
COPY --chmod=0755 run.sh /run.sh

# Robuster Entrypoint: Shell startet das Skript (um Shebang/BOM/CRLF-Probleme zu vermeiden)
ENTRYPOINT ["/bin/sh","/run.sh"]


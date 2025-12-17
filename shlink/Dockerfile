
ARG SHLINK_TAG=stable
FROM shlinkio/shlink:${SHLINK_TAG}

# Startskript mit Ausführungsrechten direkt beim Kopieren hinterlegen
COPY --chmod=0755 run.sh /run.sh

ENTRYPOINT ["/run.sh"]


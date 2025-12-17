
# HA_Addon/shlink/Dockerfile
ARG SHLINK_TAG=stable
FROM shlinkio/shlink:${SHLINK_TAG}

# Startskript ins Image und ausführbar machen
COPY run.sh /run.sh
RUN chmod +x /run.sh

# KORREKT: ENTRYPOINT, und danach NICHTS mehr!
ENTRY


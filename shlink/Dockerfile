
# Du kannst den Tag bei Bedarf pinnen (z. B. v4.6.0)
ARG SHLINK_TAG=stable
FROM shlinkio/shlink:${SHLINK_TAG}

# Nützliche Tools für das Startskript (jq, bash) installieren.
# Das Basis-OS des Shlink-Images kann Alpine oder Debian sein; wir
# versuchen zuerst apt, fallen sonst auf apk zurück.
RUN (apt-get update && apt-get install -y --no-install-recommends jq bash) || \
    (apk add --no-cache jq bash)

# Startskript ins Image
COPY run.sh /run.sh
RUN chmod +x /run.sh

# Unser Skript wird zum EntryPoint. Es setzt ENV aus HA-Optionen,
# persistiert SQLite nach /data und ruft am Ende das Shlink-Entrypoint auf.
ENTRY



# HA_Addon/shlink/Dockerfile
ARG SHLINK_TAG=stable
FROM shlinkio/shlink:${SHLINK_TAG}

# Hilfstools fürs Startskript (jq, bash) installieren – klappt auf Debian- oder Alpine-basierten Images
RUN if command -v apt-get >/dev/null 2>&1; then \
      apt-get update && apt-get install -y --no-install-recommends jq bash && rm -rf /var/lib/apt/lists/*; \
    elif command -v apk >/dev/null 2>&1; then \
      apk add --no-cache jq bash; \
    else \
      echo "No supported package manager found in base image" && exit 1; \
    fi

# Startskript ins Image und ausführbar machen
COPY run.sh /run.sh
RUN chmod +x /run.sh

# Wichtig: Hier lag der Fehler – ENTRYPOINT, nicht ENTRY
ENTRYPOINT ["/run.sh"]



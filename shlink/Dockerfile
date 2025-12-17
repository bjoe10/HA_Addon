
# Nutzt direkt das Shlink-Upstream-Image
ARG SHLINK_TAG=stable
FROM shlinkio/shFROM shlinkio/shlink:${SHLINK_TAG}

# Als root: /data beschreibbar machen und Symlink setzen
USER 0

# Startskript kopieren & CRLF->LF absichern
COPY --chmod=0755 run.sh /run.sh
RUN sed -i 's/\r$//' /run.sh

# Start über /bin/sh (robust gegen exec-format-Fehler)


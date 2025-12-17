
# syntax=docker/dockerfile:1
FROM shlinkio/shlink:stable

# Root, um /data und Symlink einzurichten
USER 0

# Startskript kopieren, CRLF -> LF absichern
COPY --chmod=0755 run.sh /run.sh
RUN sed -i 's/\r$//' /run.sh

# Robust starten (verhindert exec-format Fehler)
ENTRYPOINT ["/


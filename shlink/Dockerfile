
# HA_Addon/shlink/Dockerfile
FROM shlinkio/shlink:stable

## Unser Startskript in den Arbeitsordner des Basis-Images legen
# (Workdir/Owner ist /etc/shlink mit USER 1001; dort sind Schreibrechte vorhanden)
COPY run.sh /etc/shlink/run.sh

# Shlink API-Port (laut offizieller Doku)
EXPOSE 8080

# Starte unser Skript per /bin/sh; Executable-Bit ist damit nicht erforderlich.



# Home Assistant baut automatisch pro Architektur, wir vermeiden zusätzliche Labels,
# um Linter-Warnungen zu umgehen.

FROM shlinkio/shlink:stable

# Unser Add-on-Wrapper (liest HA-Optionen, setzt ENV, erzeugt API-Key, startet Shlink)
COPY run.sh /usr/local/bin/ha-run.sh
RUN chmod +x /usr/local/bin/ha-run.sh

## WICHTIG: Keine Paketinstallation (apk) im Shlink-Image!


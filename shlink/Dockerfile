
# Datei löschen & neu schreiben (GENAU so übernehmen)
rm -f HA_Addon/shlink/Dockerfile

cat > HA_Addon/shlink/Dockerfile <<'EOF'
FROM shlinkio/shlink:stable

# Startskript ins Image legen
COPY run.sh /usr/local/bin/run.sh
RUN chmod +x /usr/local/bin/run.sh

# Shlink API-Port (laut offizieller Doku)
EXPOSE 8080

# Start: Optionen einlesen, ENV setzen, Upstream-Entrypoint starten
CMD ["/usr/local/bin/run.sh"]
EOF
``


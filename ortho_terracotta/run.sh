#!/usr/bin/env bashio

DATA_PATH=$(bashio::config 'data_path')
bashio::log.info "Serviere Orthomosaics aus ${DATA_PATH}"

mkdir -p "${DATA_PATH}"

# Backend: Tile-Server im Ad-hoc-Modus, kein Ingest noetig.
# Jede *.tif in DATA_PATH wird automatisch unter ihrem Dateinamen sichtbar.
terracotta serve -r "${DATA_PATH}/{name}.tif" --port 5000 --allow-all-ips &

# kurz warten bis das Backend steht
sleep 3

# Frontend/Client: das ist der Ingress-Port (5100)
exec terracotta connect localhost:5000 --port 5100 --no-browser

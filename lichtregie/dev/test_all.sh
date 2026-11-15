#!/bin/sh
# Alle Tests der Lichtregie (ohne Geräte, ohne HA). Aufruf: dev/test_all.sh
cd "$(dirname "$0")/.." || exit 1
for t in test_config test_audio test_beatcount test_smoke; do
  out="$(python3 "dev/$t.py" 2>&1)" || { echo "$out"; echo "FEHLER in $t"; exit 1; }
  echo "$out" | tail -1
done
rm -rf app/__pycache__

# Orthomosaic Viewer – lokales HA Add-on (Terracotta)

## Installation

1. Ordner **`ortho_terracotta`** komplett nach `/addons/ortho_terracotta` auf
   deinem HA-OS-Host kopieren (z.B. per Samba-Add-on unter `\\<pi-ip>\addons\`,
   oder per SCP über die SSH-Add-on).
2. In HA: **Einstellungen → Add-ons → Add-on Store → oben rechts ⋮ → Check for updates**
   (oder Store neu laden). Unter "Lokale Add-ons" taucht **"Orthomosaic Viewer"** auf.
3. Installieren → Starten. Erscheint danach als eigener Punkt in der Sidebar
   (Ingress, kein extra Port nötig).

## Nutzung

- GeoTIFFs einfach in `/share/orthomosaics/` auf dem Pi ablegen
  (per Samba-Add-on oder File-Editor-Add-on erreichbar).
- Dateiname = Anzeigename, z.B. `feld_nord_2026-06.tif`.
- Neu hinzugefügte Dateien erscheinen nach einem Reload der Seite automatisch
  (kein Neustart des Add-ons nötig, da Ad-hoc-Modus ohne Datenbank-Ingest).

## Hinweise

- Für beste Performance/Ladezeit auf dem Pi 5: Dateien vorher als
  **Cloud Optimized GeoTIFF (COG)** speichern, z.B.:
  ```
  gdal_translate input.tif output.tif -of COG -co COMPRESS=DEFLATE
  ```
  Normale GeoTIFFs funktionieren auch, sind aber beim ersten Rendern
  pro Zoomstufe etwas langsamer.
- `data_path` lässt sich in den Add-on-Optionen anpassen, falls du die
  Dateien woanders unter `/share` ablegen willst.
- Terracotta selbst ist reines Python (Flask + Rasterio) – auf einem Pi 5
  (4 Kerne) für Einzelnutzer-Betrachtung problemlos performant genug.

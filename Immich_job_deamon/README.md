# Immich Job Daemon Add-on

Dieses Add-on verwaltet Immich-Jobs über die API und sorgt dafür, dass nur eine bestimmte Anzahl gleichzeitig läuft.

## Konfiguration

- `IMMICH_URL`: URL zum Immich-Server
- `API_KEY`: API-Schlüssel mit `job.read` und `job.create` Rechten
- `MAX_CONCURRENT_JOBS`: Maximale Anzahl gleichzeitiger Jobs
- `POLL_INTERVAL`: Intervall in Sekunden zur Abfrage

## Hinweise

Stelle sicher, dass dein Immich-Server erreichbar ist und die API korrekt funktioniert.

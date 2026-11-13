# Lichtregie

Musikgesteuerte Lichtshow für zwei Moving Heads als Home-Assistant-Add-on. Die Köpfe werden per Art-Net
direkt angesteuert; Titel, Tempo und Stimmung kommen aus Spotify (über HA) und der FreqBlog Music API.

- Anleitung: [DOCS.md](DOCS.md)
- Show-Design: [SHOW.md](SHOW.md), Konzept und Messwerte: [KONZEPT.md](KONZEPT.md)
- Werkzeuge für Kalibrierung und Tests: `dev/` (lokal starten mit `dev/run_local.sh`)

## Tempo-Daten

Tempo und Stimmung der Titel kommen von der [FreqBlog Music API](https://freqblog.com/music-api.html).
Ursprünglich war [GetSongBPM](https://getsongbpm.com) als Quelle vorgesehen.

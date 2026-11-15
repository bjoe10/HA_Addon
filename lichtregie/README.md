# Lichtregie

Musikgesteuerte Lichtshow für zwei Moving Heads als Home-Assistant-Add-on. Die Köpfe werden per Art-Net
direkt angesteuert; Titel, Tempo und Stimmung kommen aus Spotify (über HA) und der FreqBlog Music API.

- Anleitung: [DOCS.md](DOCS.md)
- Show-Design: [SHOW.md](SHOW.md), Konzept und Messwerte: [KONZEPT.md](KONZEPT.md)
- Entwicklung: `dev/test_all.sh` (Tests ohne Geräte), `dev/run_local.sh` (lokal starten), `dev/nachspielen.py` (Aufnahme vom Gerät
  durch die Analyse spielen), `dev/show_auswerten.py` (Stillstand und Ruckler in einer Aufnahme), `dev/messen/`
  (Werkzeuge aus der Kalibrierung)

## Beat This!

Die „1“ im Takt erkennt das Modell [Beat This!](https://github.com/CPJKU/beat_this) (Institute of Computational
Perception, JKU Linz, MIT-Lizenz, siehe `app/modelle/LIZENZ-beat-this.txt`), im Add-on in numpy nachgebaut.

## Tempo-Daten

Tempo und Stimmung der Titel kommen von der [FreqBlog Music API](https://freqblog.com/music-api.html).
Ursprünglich war [GetSongBPM](https://getsongbpm.com) als Quelle vorgesehen.

# Lichtregie

Musikgesteuerte Lichtshow für zwei Moving Heads, einen Laser und Lampen als Home-Assistant-Add-on. Die Köpfe werden
per Art-Net direkt angesteuert. Ton, Titel und Position im Lied kommen über einen eigenen AirPlay-Empfänger (Music
Assistant), Tempo und Stimmung aus der FreqBlog Music API, Schlag und „1“ aus der Live-Analyse und Beat This!.

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

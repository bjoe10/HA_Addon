# Lichtregie

Musikgesteuerte Lichtshow für zwei Moving Heads. Das Add-on liest den laufenden Spotify-Titel aus Home
Assistant, holt Tempo, Tonart und Stimmung aus der FreqBlog Music API und steuert die Köpfe direkt per Art-Net:
Bahnen auf Boden, Wänden und Decke, Farben, Gobos, Dimmer-Pulse und Strobe im Takt. Jedes Lied bekommt ein
festes Thema, dasselbe Lied sieht also jedes Mal gleich aus.

> **Hinweis:** Die Show nutzt Strobe-Blitze. Sie lassen sich in der Oberfläche abschalten. Blitzlicht kann
> für Menschen mit photosensitiver Epilepsie gefährlich sein.

## Was du brauchst

- **Art-Net-Nodes** für die Köpfe, eingerichtet über die HA-Plattform `artnet_led` in der `configuration.yaml`.
  Das Add-on liest daraus Host, Universe und die Kanäle `pan`, `tilt`, `color`, `Grobo`, `strobe`, `dimmer`,
  `motor speed`, `auto mode`, `config mode` (Kopf 2 jeweils mit `2` am Ende). Pan und Tilt sind 16 Bit.
- Die **Spotify-Integration** in HA (ein `media_player` mit Titel und Position).
- Einen **FreqBlog-API-Schlüssel** (freqblog.com, kostenloser Tarif).

## Einrichtung

1. Add-on installieren, in der Konfiguration **Spotify-Player** (z. B. `media_player.spotify_name`) und den
   **FreqBlog-API-Schlüssel** eintragen, starten, „In Seitenleiste anzeigen“ aktivieren.
2. Im Add-on-Log prüfen, dass beide Köpfe aus der `configuration.yaml` erkannt wurden
   (`Kopf 1: Node …, Kanäle … (configuration.yaml)`).
3. Die Köpfe einschalten (Steckdosen) und **alte Party-Automationen ausschalten**, die dieselben Kanäle steuern.
   Solange die Lichtregie sendet, darf HA die Köpfe nicht gleichzeitig steuern.
4. Optional die **Lampen** eintragen (Listen von `light.`-Entitäten): Grundfarbe, Akzentfarbe und
   „Während der Show aus“. Sie laufen langsam mit (Wechsel etwa alle 15 s), ihr alter Zustand kommt nach der
   Show zurück.
5. „Lichtregie“ in der Seitenleiste öffnen, Musik über Spotify starten, **Start** drücken.

## Live-Audio über Music Assistant (empfohlen)

Mit Audio rastet die Show auf den echten Schlag ein und erkennt Breaks und Drops live.

1. In der Add-on-Konfiguration **AirPlay-Empfänger** eingeschaltet lassen (Name standardmäßig „Lichtregie“).
2. In **Music Assistant** erscheint ein AirPlay-Player „Lichtregie“. Ihn mit dem Lautsprecher (ebenfalls über
   AirPlay) zu einer **Sync-Gruppe** zusammenfassen und die Musik auf die Gruppe spielen, z. B. über das
   Spotify-Connect-Plugin von Music Assistant.
3. In der Oberfläche zeigt „Audio: Takt eingerastet“, dass es funktioniert. Zum Abgleich **Takt-Test** einschalten:
   Die Köpfe blitzen auf jedem Schlag. Kommt der Blitz vor dem Kick, Audio-Versatz nach links (minus),
   kommt er danach, nach rechts (plus). Danach Takt-Test wieder aus.

Ohne Audio (z. B. Spotify direkt auf den Lautsprecher) läuft die Show mit Tempo aus der Datenbank weiter.

## Oberfläche

- **Raum antippen:** Das Bild zeigt den Raum aus Sicht der Kopfwand. Antippen richtet beide Köpfe auf den Punkt
  auf Boden, Wand oder Decke. Während der Show erscheinen dort die Spots als Vorschau.
- **Show:** Start/Stopp, Schalter für Strobe, Nebel (mehr Strahl-Effekte), Bewegung ×1/×2, Anschub und
  Vorsteuerung, Lampen, Lampen-Vorlauf, Audio, Audio-Versatz. Die Schalter bleiben über einen Neustart erhalten.
- **Kopf 1/2:** Pan, Tilt, Helligkeit, Farbe, Gobo und Strobe einzeln, mit Namen der Farben und Muster.

Kommt bei laufender Show und spielendem Spotify 15 s lang kein Ton am AirPlay-Empfänger an, warnt die
Oberfläche oben in Rot und HA zeigt eine Benachrichtigung. Meist fehlt der Empfänger nach einem Neustart des
Add-ons in der Sync-Gruppe von Music Assistant: dort wieder aufnehmen und das Lied neu starten.

Der Titelwechsel wird alle 2 Sekunden geprüft. Neue Titel kennt FreqBlog manchmal noch nicht; dann startet die
Show ein paar Sekunden später von selbst.

## Grenzen

- Die Raumgeometrie und die Kalibrierung der Köpfe sind für ein bestimmtes Wohnzimmer eingestellt
  (`app/geometry.py`). In einem anderen Raum muss neu kalibriert werden (siehe `dev/` im Repository).
- Wo der erste Schlag eines Liedes liegt, ist unbekannt. Bahnen laufen im Tempo, Pulse können leicht versetzt sein.
- Kein Audio: Drops und Breaks werden aus Liedlänge und Phrasen geschätzt.

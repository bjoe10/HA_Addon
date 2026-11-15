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
3. **Alte Party-Automationen ausschalten**, die dieselben Kanäle steuern. Solange die Lichtregie sendet,
   darf HA die Köpfe nicht gleichzeitig steuern.
4. Optional **Geräte der Party** eintragen: Schalter, die der Party-Modus ein- und am Ende wieder ausschaltet,
   z. B. die Steckdosen der Köpfe (`switch.`, `input_boolean.`, `light.`). Die **Laser-Steckdose** gehört
   automatisch dazu.
5. Optional die **Lampen** eintragen: Grundfarbe und Akzentfarbe (`light.`) laufen mit der Show mit
   (Farbwechsel alle 8 oder 16 Takte). Bei „Akzentfarbe“ steht die erste Lampe links vom TV, die zweite rechts;
   die beiden spielen im Wechsel, jede weitere folgt der Akzentfarbe. „Während der Party aus“ (auch `switch.`) wird ausgeschaltet. Nach der
   Party kommt der alte Zustand zurück.
6. „Lichtregie“ in der Seitenleiste öffnen und Musik starten. Mit Automatik geht die Party von selbst an.

## Live-Audio über Music Assistant (empfohlen)

Mit Audio rastet die Show auf den echten Schlag ein und erkennt Breaks und Drops live.

1. In der Add-on-Konfiguration **AirPlay-Empfänger** eingeschaltet lassen (Name standardmäßig „Lichtregie“).
2. In **Music Assistant** erscheint ein AirPlay-Player „Lichtregie“. Ihn mit dem Lautsprecher (ebenfalls über
   AirPlay) zu einer **Sync-Gruppe** zusammenfassen und die Musik auf die Gruppe spielen, z. B. über das
   Spotify-Connect-Plugin von Music Assistant.
3. Auf der Startseite zeigt die Kachel „Audio: Takt sitzt“, dass es funktioniert. Zum Abgleich unter
   Feinabstimmung den **Takt-Test** einschalten:
   Die Köpfe blitzen auf jedem Schlag. Kommt der Blitz vor dem Kick, Audio-Versatz nach links (minus),
   kommt er danach, nach rechts (plus). Danach Takt-Test wieder aus.

Ohne Audio (z. B. Spotify direkt auf den Lautsprecher) läuft die Show mit Tempo aus der Datenbank weiter.

## Party-Modus

Der Party-Modus ist der Hauptschalter. **An:** Geräte einschalten, Raum abdunkeln, laufenden Titel lesen,
Show starten. **Aus:** Show stoppen, Köpfe dunkel, Geräte aus, Lampen zurück auf den Zustand von vorher.

- **Automatik** (abschaltbar): Die Party geht an, sobald 3 s lang Musik ankommt (Ton am AirPlay-Empfänger;
  ohne Empfänger: Spotify spielt), und aus, wenn 15 Minuten keine lief (Zeit einstellbar).
- **Von Hand:** großer Schalter auf der Startseite. Ein Stopp von Hand gilt, bis die Musik einmal eine Minute
  aus war; sonst würde die Automatik sofort wieder einschalten.
- **Pause:** Pausiert Spotify, bleiben die Spots stehen und leuchten leise, der Laser geht aus.
- **Überspringen und Spulen:** Ein neuer Titel wird nach spätestens 2 s erkannt. Spulen im Lied (Sprung über
  5 s) setzt die Schlagzählung neu auf, sobald HA die neue Position meldet.
- **Titel unbekannt:** Kennt FreqBlog das Lied nicht oder meldet HA keinen Titel, läuft die Show mit dem Tempo
  aus dem Audio.
- Ein Neustart des Add-ons (z. B. Update) unterbricht die Party nicht: Sie läuft danach weiter.

## Oberfläche

- **Show** (Startseite): Party-Schalter, laufendes Lied mit seinem Thema (Tempo, Stimmung, Farben, Gobos,
  Laser-Rolle) und Schlaganzeige, **Thema neu würfeln** (das neue Thema bleibt für dieses Lied gespeichert),
  Status auf einen Blick (Audio, Spotify, Geräte, Lampen, Laser), Vorschau der Spots im Raumbild, Schalter
  für den Abend: Strobe, Nebel (mehr Strahl-Effekte), Laser, Lampen und ihre Helligkeit, Automatik.
- **Feinabstimmung:** Audio und Takt-Test mit Audio-Versatz, Lampen-Vorlauf, Bewegungstempo, Anschub und
  Vorsteuerung, Laser-Bereich (Grenzen und Show-Mitte), Zeit bis zum automatischen Aus.
- **Einrichten:** Raum antippen (beide Köpfe zielen auf den Punkt), einzelne Kanäle der Köpfe und des Lasers
  von Hand, Laser-Steckdose. Nur sinnvoll, solange die Party aus ist.

Alle Schalter bleiben über einen Neustart erhalten.

Kommt bei laufender Show und spielendem Spotify 15 s lang kein Ton am AirPlay-Empfänger an, warnt die
Oberfläche oben in Rot und HA zeigt eine Benachrichtigung. Meist fehlt der Empfänger nach einem Neustart des
Add-ons in der Sync-Gruppe von Music Assistant: dort wieder aufnehmen und das Lied neu starten.

## Grenzen

- Die Raumgeometrie und die Kalibrierung der Köpfe sind für ein bestimmtes Wohnzimmer eingestellt
  (`app/geometry.py`). In einem anderen Raum muss neu kalibriert werden (siehe `dev/messen/` im Repository).
- Ohne Audio ist unbekannt, wo der erste Schlag liegt: Bahnen laufen im Tempo, Pulse können leicht versetzt
  sein, Drops und Breaks werden aus Liedlänge und Phrasen geschätzt.

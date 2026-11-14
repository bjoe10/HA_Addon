# Changelog

## 0.6.0

- Takt- und Phrasen-Sync: Mit eingerastetem Audio zählt die Lichtregie die Schläge selbst weiter
  (`beatcount.py`); Sprünge der Spotify-Position schlagen nicht mehr durch, nur dauerhafte grobe Abweichungen
  (über 6 Schläge, länger als 8 s) werden übernommen.
- Drop als Anker: Ein erkannter Drop wird auf die nächste Phrasengrenze (32 Schläge) gelegt, höchstens ±12
  Schläge Verschiebung.
- Phrasenwechsel-Erkennung in der Audioanalyse (Klangvergleich der letzten 2 s mit den 6 s davor in 8
  Frequenzbändern); liegt ein Wechsel bis zu 3 Schläge neben der erwarteten Grenze, wird nachgezogen.
- Szenen-Zeile zeigt Takt.Schlag und kurz jede Korrektur.
- Lampen wechseln je Lied alle 8 oder 16 Takte (ruhige Lieder eher 16), mit einstellbarem Vorlauf
  (Standard 0,8 s) wegen der Reaktionszeit der Yeelights; Übergang 0,5 s.
- Laser-Rolle je Lied: aus, nur Höhepunkte (Aufbau, Höhepunkt, Drop), jede zweite Phrase oder durchgehend,
  gewichtet nach Stimmung (ruhige Lieder meist ohne Laser).
- Laser-Ruhepunkt in der Show über dem TV (Hoch/runter 76 statt Wandmitte 64), Bahnen bleiben über dem TV;
  einstellbar mit „Show-Mitte hoch/runter“ in der Laser-Karte (unter die Mitte gestellt: Bahnen unter dem TV).

## 0.5.0

- Laser in der Show: jedes Lied bekommt ein Laser-Thema (Hauptform, Nebenform, Gag-Symbol, drei Laser-Szenen).
  Farbe aus dem Liedthema, Mischfarben auf Höhepunkt und Drop, Drehung und Münz-Kippen im Takt, Größen-Puls
  auf dem Schlag (kräftiger mit eingerastetem Audio), Position in den Schutzgrenzen, gestrichelt im Break,
  Countdown „3, 2, 1“ vor dem Höhepunkt. Beim Stopp geht der Laser aus.
- Laser-Kanäle am Gerät vermessen (siehe SHOW.md); Standardgrenzen hoch/runter 42–86, links/rechts 39–90.
- Formnamen in der Laser-Karte.

## 0.4.0

- Laser-Testwerkzeug: Karte in der Oberfläche mit allen 10 Laserkanälen, „Party-Standard laden“, Steckdose
  an/aus (Option `laser_schalter`) und Schutzgrenzen für hoch/runter und links/rechts, die auf jeden
  gesendeten Wert wirken. Laser-Node und Kanäle aus der `configuration.yaml`.
- Senden an den Laser ist nach jedem Neustart aus; solange es aus ist, bleibt der Laser bei HA.
- Noch nicht in der Show: erst messen und Grenzen festlegen.

## 0.3.2

- Mit eingerastetem Audio-Takt kräftigere Effekte: Pulse fallen auf 25 % statt 50 %, konstante Szenen pulsieren
  bei mittleren und druckvollen Liedern, Strobe auf jeder „1“ der ersten vier Takte von Höhepunkt und Drop,
  Strobe-Wirbel im letzten Takt des Aufbaus. Ohne Audio bleibt es bei den weichen Effekten.
- Audio-Versatz standardmäßig 80 ms (am Gerät gemessen).
- Regler „Lampen Decke“ und „Lampen Vitrinen“ (0–150 %) für die Helligkeit der beiden Lampengruppen,
  Standard Decke 40 %, Vitrinen 100 %.

## 0.3.1

- Takt-Test zum Einstellen des Audio-Versatzes: beide Köpfe weiß auf die TV-Wand, kurzer voller Blitz auf
  jedem Schlag, sonst fast dunkel.

## 0.3.0

- Live-Audioanalyse: AirPlay-Empfänger im Add-on (shairport-sync). In Music Assistant mit dem Lautsprecher
  gruppiert, hört die Lichtregie dieselbe Musik synchron mit.
- Schlagphase aus den Kicks (Phasenregler, Tempo aus der Datenbank als Vorgabe), Pegel, Break- und
  Drop-Erkennung. Drop startet sofort einen Höhepunkt mit Blitz, Break eine ruhige Phase; Lampen folgen.
- Ohne Audio läuft die Show wie bisher. Schalter „Audio an/aus“ und Audio-Versatz in der Oberfläche.
- Das Add-on nutzt jetzt das Host-Netzwerk (für AirPlay/mDNS), Ingress-Port 8475. Die Oberfläche nimmt nur
  Anfragen über den HA-Ingress an.
- Lampen: Die gesicherte Szene wird nach dem Stopp nach 5 s ein zweites Mal aufgerufen (Yeelights verschlucken
  gelegentlich einen Befehl).

## 0.2.0

- Lampen über HA als langsame Ebene: Grundfarbe (z. B. Ambilight-Ringe) und Akzentfarbe (z. B. Vitrinen)
  nach dem Song-Thema, Wechsel pro Phrase, heller auf Höhepunkten, gedimmt in der Atempause.
- Hauptlicht kann während der Show ausgeschaltet werden; der Zustand aller Lampen wird vorher als Szene
  gesichert und nach der Show wiederhergestellt.
- Schalter „Lampen an/aus“ in der Oberfläche.

## 0.1.0

- Erste Fassung als Add-on: Show-Motor, Web-Oberfläche in der Seitenleiste (Ingress).
- Art-Net-Nodes und Kanäle werden aus der HA-`configuration.yaml` gelesen (`artnet_led`).
- Spotify-Titel aus HA, Tempo und Stimmung über die FreqBlog Music API.
- Song-Thema je Titel, 15 Bahnformen auf Boden, Wand und Decke, Dimmer-Pulse, kurze Strobes,
  Anschub und Vorsteuerung gegen die träge Mechanik der Köpfe.

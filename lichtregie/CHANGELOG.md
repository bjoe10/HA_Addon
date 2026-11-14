# Changelog

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

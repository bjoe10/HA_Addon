# Changelog

## 0.8.1

- Ambilights wechseln alle 8 oder 16 Takte durch drei Farben des Liedes (Grund, Akzent, Gegenfarbe) statt nur
  zwischen zwei; die Schränke laufen einen Schritt versetzt. Das fällt deutlich mehr auf.
- Schrank 1 (links vom TV) und Schrank 2 (rechts) spielen unabhängig im Wechsel: pro Takt ist einer hell, der
  andere auf 20 % gedimmt. Auf Höhepunkt und Drop leuchtet alles in der Akzentfarbe, im Break und in der
  Atempause beide ruhig. Reihenfolge in „Lampen Akzentfarbe“: erste Lampe = links, zweite = rechts, weitere
  folgen der Akzentfarbe.
- Yeelights hängen lokal, deshalb Übergang 0,4 s statt 0,5 s und häufigere Wechsel.

## 0.8.0

- **Party-Modus** als Hauptschalter: an = Geräte einschalten (neue Option „Geräte der Party“ plus
  Laser-Steckdose), Raum abdunkeln, Show; aus = Show stoppen, Köpfe dunkel, Geräte aus, Lampen zurück.
- **Automatik:** an, sobald 3 s Musik ankommt; aus nach 15 Minuten ohne Musik (einstellbar). Ein Stopp von
  Hand gilt, bis die Musik eine Minute aus war. Der Party-Stand überdauert einen Neustart des Add-ons.
- **Neue Oberfläche** in drei Bereichen: Show (Party-Schalter, Lied und Thema, Status auf einen Blick,
  Vorschau, Schalter für den Abend), Feinabstimmung, Einrichten.
- **Thema neu würfeln** für das laufende Lied; die Variante bleibt für dieses Lied gespeichert.
- Pause: Spots bleiben stehen und leuchten leise, Laser aus. Meldet HA keinen Titel, startet die Show mit dem
  Tempo aus dem Audio; dazu ein Hinweis in der Oberfläche.
- „Während der Party aus“ nimmt auch Schalter (`switch.`, `input_boolean.`). Die Lampen bleiben zwischen
  zwei Liedern, wie sie sind, statt kurz auf den alten Zustand zu springen.
- Beim Start des Add-ons bleiben die Köpfe dunkel, bis die Party läuft.
- Entfallen: Start mit Titel/BPM von Hand.

## 0.7.0

Aufräumen ohne Änderung an der Show:

- Server in Module zerlegt: `engine.py` (Show-Motor), `heads.py`, `laser.py`, `lamps.py`, `ha.py`,
  `settings.py`; `server.py` ist nur noch Web-Schicht und Start. Die Oberfläche liegt als eigene Dateien in
  `app/web/`.
- Neuer Rauchtest (`dev/test_smoke.py`): Show-Motor und Web-Schnittstelle ohne Geräte und ohne HA;
  `dev/test_all.sh` startet alle Tests. Messwerkzeuge aus der Einrichtung liegen in `dev/messen/`.
- Doku auf den aktuellen Stand gebracht (SHOW.md: Aufbau der Software, Stand der Umsetzung).
- Spulen im Lied: Springt die Liedposition um mehr als 5 s, setzt die Schlagzählung sofort neu auf
  (bisher erst nach 8 s Abweichung). Überspringen wurde schon bisher nach spätestens 2 s erkannt.
- Laser standardmäßig an: Das Senden an den Laser ist nicht mehr nach jedem Neustart aus, sondern behält die
  Einstellung aus der Oberfläche (Standard: an). Ohne laufende Show bleibt der Laser aus (Modus 0); solange
  das Senden an ist, kann HA den Laser nicht steuern.

## 0.6.1

- Warnung, wenn kein Audio ankommt: Spielt Spotify und läuft die Show, aber am AirPlay-Empfänger kommt
  15 s lang kein Ton an, erscheint ein roter Hinweis oben in der Oberfläche und eine HA-Benachrichtigung
  („Lichtregie: kein Audio“). Beides verschwindet, sobald wieder Ton kommt. Häufigste Ursache: der
  Empfänger ist nach einem Neustart des Add-ons nicht mehr in der Sync-Gruppe von Music Assistant.
- Liedübergänge: Die Show läuft bis kurz vor Schluss voll weiter. Das Outro (Spots laufen zusammen) kommt nur
  in den letzten 2 Takten und dimmt höchstens auf 60 %; früher (bis 12 Takte vorher) nur, wenn das Audio zeigt,
  dass die Musik ausläuft. Bisher wurde schon 8 Takte vor Ende auf 30 % heruntergefahren.
- Setzt das nächste Lied gleich voll ein (Live-Audio), entfällt das ruhige Intro.
- Kennt FreqBlog ein Lied nicht, bleibt die Show nicht mehr dunkel stehen: Sie läuft weiter, bis das Audio
  das Tempo sicher erkannt hat (frühestens nach 8 s), und startet dann damit. FreqBlog wird dabei nur noch
  alle 20 s erneut gefragt.
- Puls durch Abdunkeln: Mit eingerastetem Audio-Takt dunkeln die Köpfe kurz vor jedem Schlag ganz ab (letztes
  Drittel des Schlags) und sind auf dem Kick schlagartig voll da, statt auf dem Kick hoch- und danach
  abzudimmen. Neue Muster `vorher`, `vorher_halb` (jeder 2. Schlag), `vorher_wechsel` (Köpfe abwechselnd).
  „puls“, „halbzeit“ und „konstant“ werden mit Audio dazu; ruhige Lieder pulsen leicht auf jedem 2. Schlag.
  Mittel/druckvoll pulsen damit in rund zwei Dritteln der Zeit auf dem Takt. Ohne Audio bleibt es wie bisher.

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

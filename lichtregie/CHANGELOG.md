# Changelog

## 0.8.9

- **Schlagzählung repariert:** Am Gerät sprang die Zählung alle 11 s um +25 Schläge („HA-Abgleich“), Takt und
  Phrase passten dadurch nie zur Musik. Ursache: Gezählt wurde über die Phasensprünge von Bild zu Bild; lief
  die Show-Schleife auf dem Pi mit unter ~5 Bildern/s, gingen Schläge verloren. Jetzt wird aus der vergangenen
  Zeit vorhergesagt und auf die gemessene Phase eingerastet: richtig bei jeder Bildrate (Test bis 1,3 s
  Bildabstand).
- HA-Abgleich schaltet sich für das Lied ab, wenn er zweimal kurz hintereinander in dieselbe Richtung korrigieren
  müsste (Tempo aus der Datenbank passt nicht zum Audio); dann zählt nur das Audio.
- Audioanalyse hält ihre Sperre nur noch je Hop: Kommt Ton in großen Blöcken, blockierte sie die Show-Schleife
  (wahrscheinliche Ursache der niedrigen Bildrate).
- Bildrate der Show in der Takt-Sync-Anzeige (Soll 40/s, Hinweis unter 25).

## 0.8.8

- Fehler behoben: Sobald Ton ankam, stürzte die Status-Abfrage der Oberfläche ab (numpy-Zahl aus der
  Audioanalyse nicht als JSON sendbar). Startseite, Vorschau und Status blieben dadurch stehen.

## 0.8.7

- **Empfänger auf stdout umgestellt:** Am Gerät meldete shairport-sync (beim Neubau jetzt Version 5.5.1) eine
  laufende Wiedergabe von Music Assistant, in der Pipe kam aber kein Byte an. Die Lichtregie startet
  shairport-sync jetzt selbst mit dem Ausgang „stdout“ und liest den Ton direkt (Format fest S16_LE, 44,1 kHz,
  stereo). Endet shairport-sync, startet die Lichtregie es nach 3 s neu; seine Meldungen stehen im Add-on-Log.

## 0.8.6

- Kein automatischer Neustart des Empfängers mehr: Am Gerät zeigte sich, dass Music Assistant einen
  Empfänger, der sich während der Wiedergabe neu anmeldet, nicht wieder in den laufenden Stream aufnimmt. Der
  Neustart hat ihn also aus dem Stream geworfen statt zu helfen. Die Warnung sagt stattdessen, was zu tun ist.

## 0.8.5

- **Empfänger zuverlässiger:** Die Lichtregie hält die Audio-Pipe jetzt dauerhaft offen (lesen und schreiben).
  Bisher gab es nach jedem Ende einer Wiedergabe einen kurzen Moment ohne Leser; öffnete shairport-sync die
  Pipe genau dann (Liedwechsel, Gruppe in Music Assistant neu gestartet), verwarf es den Ton der ganzen
  Wiedergabe. Im Test passierte das bei 11 von 20 schnellen Wechseln, mit dem neuen Leser bei keinem.
- Start der Party weiterhin nur durch Ton am Empfänger. Läuft sie schon, hält sie auch Spotify am Leben, damit
  sie bei einer Störung des Empfängers nicht ausgeht.
- Warnung auch bei ausgeschalteter Party: Spielt Spotify über Music Assistant und am Empfänger kommt nichts an,
  sagt die Oberfläche, was zu tun ist. shairport-sync läuft in einer Schleife und kommt nach einem Absturz wieder.
- Diagnose: Kachel „Audio“ unterscheidet „kein Signal“ von „Daten, aber stumm“, die Warnung nennt die Ursache;
  shairport-sync schreibt Verbindungen und Wiedergabe-Start ins Add-on-Log.
- Neuer Test `dev/test_pipe.py` (Liedwechsel an der Pipe wie mit shairport-sync).

## 0.8.4

- **Takt-Sync-Anzeige** unter Feinabstimmung: eine Phrase als 8 Takte à 4 Schläge, der aktuelle Schlag
  leuchtet (die 1 jedes Takts weiß, der Phrasenanfang markiert), dazu Quelle (Audio oder Spotify-Position)
  und die letzten Korrekturen („Drop-Anker +3“). Stimmt der Einsatz nicht, z. B. nach einem Break: im Moment
  der echten 1 „Jetzt ist die 1“ tippen (Takt oder Phrase) oder um ±1 Takt / ±1 Schlag verschieben. Die
  Verschiebung gilt für das laufende Lied.
- Der Takt-Test zeigt jetzt auch den Takt: die 1 blitzt auf beiden Köpfen, die Schläge 2–4 nur auf Kopf 1
  und schwächer, die 1 der Phrase (alle 8 Takte) doppelt so lang.
- Strobe-Menge als Regler (0–200 %, Standard 100 %) unter „Heute Abend“: darunter fallen geplante Blitze
  weg (0 = keine), darüber kommen kurze Blitze auf der „1“ dazu, mehr in Aufbau, Höhepunkt und Drop, bei
  200 % auch in normalen Szenen. Anteil der Zeit mit Strobe im Test bei druckvollen Liedern: 0 / 2 / 6 / 8 / 9 %
  bei 0 / 50 / 100 / 150 / 200 %. Der Schalter „Strobe“ bleibt der Hauptschalter.

## 0.8.2

- Party aus: Die Köpfe fahren erst dunkel in die Parkposition (Pan 0, Tilt 0, wie im alten Skript „Moving Head
  off“), damit beide gleich hängen; nach 3,5 s gehen die Steckdosen aus.

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

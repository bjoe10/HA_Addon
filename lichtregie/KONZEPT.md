# Lichtregie – Konzept

Ein Home-Assistant-Add-on auf dem Raspberry Pi 5, das die Lichtshow im Wohnzimmer
musikgesteuert macht: beide Moving Heads zielen auf echte Punkte im Raum, der Laser
folgt der Musik, RGB-Lampen und LED-Streifen hinter dem TV laufen mit.

Status: **Konzept, noch kein Code.** Offene Fragen stehen ganz unten.

---

## 1. Ausgangslage (aus HA gelesen)

| Gerät | Entitäten (Auszug) | Anmerkung |
|---|---|---|
| Moving Head 1 | `light.pan`, `light.tilt`, `light.color`, `light.strobe`, `light.grobo` | Jeder DMX-Kanal ist eine eigene Dimmer-Entität (0–255) |
| Moving Head 2 | `light.pan2`, `light.tilt2`, `light.color2`, `light.strobe2`, `light.grobo2` | Bestätigt durch die Party-Automationen |
| Laser (RGB) | `light.laser_color`, `laser_left_right`, `laser_mirror_hori/vert`, `laser_mode`, `laser_rotate`, `laser_shape`, `laser_size` | `light.laser_color` hat `dmx_channels: [31]` |
| RGB-Laser an/aus | `script.rgb_laser_on/off`, `number.rgb_laser_countdown` | |
| Wohnzimmer-Ambilight (LED-Streifen hinter TV) | `light.wohnzimmer_1_ambilight`, `light.wohnzimmer_2_ambilight` | Haben den Effekt „Strobe color“, also vermutlich adressierbarer Streifen (WLED o. ä.), siehe Frage 4 |
| Astronaut-Licht | `input_boolean.astronaut` | wird vom Party-Modus mitgeschaltet |
| Anwesenheit | `input_boolean.anwesenheit_wohnzimmer` | taugt als Startbedingung |
| Party-Automationen (Blueprint `Twanne/party_lights.yaml`) | Ziele: `light.pan`, `light.pan2`, `light.tilt`, `light.tilt2`, `light.strobe`, `light.strobe2`, `light.grobo`, `light.grobo2`, `light.color`, `light.color2`, `light.laser_mode`, `light.laser_shape` | Zufallsbewegung, gesteuert über `input_boolean.light_random_loop` |
| Party-Hauptautomation | `automation.moving_heads_on_off` | Schaltet bei `input_boolean.moving_heads` die Scripts `moving_head_on/off`, `rgb_laser_on/off`, die Szenen `moving_head_standard` und `laser_party_standard` sowie Ambilight-Strobe und Astronaut |

### Art-Net-Konfiguration (aus `configuration.yaml`)

Drei Nodes, alle auf **Universe 1**, alle über den HA-Platform `artnet_led` im Modus `artnet-direct`:

| Node-IP | Gerät | Kanäle |
|---|---|---|
| `192.168.178.144` | Moving Head 1 | pan 1–2 (16 Bit), tilt 3–4 (16 Bit), color 5, grobo 6, strobe 7, dimmer 8, motor speed 9, auto mode 10, config mode 11 |
| `192.168.178.146` | Moving Head 2 | pan2 12–13 (16 Bit), tilt2 14–15 (16 Bit), color2 16, grobo2 17, strobe2 18, dimmer2 19, motor speed2 20, auto mode2 21, config mode2 22 |
| `192.168.178.195` | Laser | laser_mode 23, shape 24, rotate 25, mirror_hori 26, mirror_vert 27, up_down 28, left_right 29, size 30, color 31, speed_dots 32 |

Weitere Punkte aus der Config:
- `max_fps: 25` und `refresh_every: 0`: HA sendet nur bei Änderungen, nicht periodisch. Das ist gut,
  denn es gibt keinen Dauer-Sender, der mit unserem kämpft.
- Pan und Tilt sind 16 Bit breit, also 65 536 Schritte. Das ist deutlich feiner als gedacht.
- Die Kanäle `auto mode` (10, 21) und `config mode` (11, 22) müssen auf manuell stehen, sonst läuft
  der Kopf eigene Programme. Das prüfen wir im Test gegen das Handbuch.
- Die Dummy-Kanäle `my_dimmer*` auf Node 146 und die Laserkanäle sind nicht Teil der ersten Version.

**Abgleich mit HA (12.11.2026, Live-Werte `dmx_values`):**
- Die Entitäten passen zur `config.yaml`: `light.tilt` auf Kanal 3, `light.tilt2` auf 14, `light.auto_mode` auf 10,
  `light.config_mode` auf 11, `light.motor_speed` auf 9, `light.dimmer` auf 8, `light.strobe` auf 7,
  `light.grobo` auf 6, `light.pan2` auf 12.
- Auto mode und config mode stehen auf 0. Die Köpfe laufen also nicht in eigenen Programmen.
- Dimmer steht auf 255, Strobe auf 0, Gobo auf 120.
- Achtung: Der Attributwert `bright` kann vom gesendeten Wert abweichen. Maßgeblich ist `dmx_values`.

Alle Party-Automationen müssen im Show-Betrieb pausieren, sonst kämpfen sie gegen den Sender.
Die Hauptautomation schaltet zudem das Ambilight, das die Show nicht übernehmen soll; das
muss die Lichtregie bewusst entscheiden.

Der Wechselrichter-Hausakku-Planer (`hausakku_planer/`) ist ein anderes Projekt; diese Lichtregie
bekommt einen eigenen Ordner im selben Repo und dieselbe Add-on-Struktur (`config.yaml`,
`Dockerfile`, `run.sh`, `app/`).

## 2. Grundentscheidung: Art-Net direkt, nicht über HA

Über die HA-Entitäten geht jeder Kanal als eigener Service-Call durch HA und den Art-Net-Node
über WLAN. Ein Frame mit 2 Köpfen × 5 Kanälen plus Laser kommt so auf zwanzig und mehr Aufrufe.
Das ist für Musik (Takt, Strobe) zu langsam und zu unruhig.

Stattdessen sendet das Add-on **ArtDMX-Pakete (UDP, Port 6454) direkt an den Node**, mit 30–40
Bildern pro Sekunde. Art-Net ist einfach: ein Paket pro Universe und Frame. Die Kanalbelegung
liest das Add-on einmal beim Start aus den Attributen `dmx_channels` der HA-Entitäten. Eine
Hand-Kanaltabelle ist dann nicht nötig.

HA bleibt für alles, was träge sein darf: Modus-Auswahl, Status, Schalter, Dashboard-Sensoren,
Anwesenheit, Zigbee-/WLAN-Lampen.

**Zu testen (Phase 1):** Verträgt der Node Pakete von zwei Sendern? Die HA-Integration schreibt
selbst weiter. Ein Test zeigt, ob der Node die Werte mischt (HTP) oder den letzten gewinnen lässt
(LTP). Im Show-Betrieb müssen die bestehenden Party-Automationen angehalten sein, sonst kämpfen
sie gegen den Sender.

## 3. Wo zeigen die Köpfe hin? Räumliches Modell und Kalibrierung

Die Köpfe wissen nicht von selbst, wo der Raum ist. Das muss man ihnen einmal beibringen:

1. **Raummodell:** Raum in Metern (x = Breite, y = Tiefe, z = Höhe). Punkte wie „TV-Mitte“,
   „Sofa-Sitzfläche“, „Decke links“ und „Wand rechts“ sind benannt.
2. **Fixture-Position:** Jeder Kopf hat eine Position P (x, y, z) und eine Ausrichtung.
3. **Kalibrierung:** Der Nutzer fährt einen Kopf per Schieberegler auf einen bekannten Punkt
   („Nun auf TV-Mitte“) und bestätigt. Bei 5–6 Punkten pro Kopf fittet das Add-on das Modell:
   Position, Pan-/Tilt-Offset und -Skalierung sowie Umkehrung. Danach gilt:
   Zielpunkt T → Richtung (T − P) → Pan/Tilt in DMX-Werten.
4. **Konvergenz:** Beide Köpfe bekommen denselben Zielpunkt T. Das ist die Grundlage für
   „beide leuchten auf einen Punkt“. Mit T lässt sich jeder Effekt beschreiben.
5. **Phase später, optional:** Auto-Kalibrierung per Kamera. Das Add-on fährt den Kopf ab,
   erkennt den hellsten Fleck im Kamerabild (die 360-cam oder stall_cam sind schon in HA) und
   fittet das Modell selbst.

**Präzision:** Pan und Tilt sind 16 Bit breit (ch 1–2 und 3–4 bzw. 12–13 und 14–15). Das sind
65 536 Schritte über den Schwenkbereich, also praktisch stufenlos. Die Genauigkeit bestimmt dann
die Kalibrierung, nicht der Kanal.

**Kalibrierpunkte** (Werte aus HA, `dmx_values` 16 Bit, Feinkanal bisher 0):

| Punkt | Kopf 1 pan / tilt | Kopf 2 pan2 / tilt2 |
|---|---|---|
| 1: TV-Mitte | 41216 / 7168 | 24832 / 58112 |
| 2: rechte Ecke oben an der TV-Wand | 43776 / 3840 | 26880 / 61952 |
| 3: linke Ecke oben an der TV-Wand | 39168 / 2560 | 22272 / 62720 |
| 4: kleiner Tisch im Raum | 38400 / 15104 | 27392 / 50176 |
| 5: Mitte der Decke (nachgestellt) | 39168 / 768 | 26880 / 64512 |

**Erster Fit** (`lichtregie/dev/kalibrierung_fit.py`, Zielkoordinaten geschätzt):
- Kopf 1 steht vermutlich rechts (x ≈ 4,9 m, y ≈ 5,4 m, z ≈ 2,3 m), Kopf 2 links (x ≈ 0,1 m, y ≈ 5,1 m, z ≈ 2,2 m).
- Die Abweichung liegt bei etwa 4° (Kopf 2) bis 7° (Kopf 1) im Pan. Das sind rund 0,4 bis 0,7 m auf 6 m Entfernung. Zu grob für die Show.
- Kopf 1 hat bei Punkt 4 (Tisch) und 5 (Decke) denselben Pan-Wert (38400). Das passt geometrisch nicht zu zwei verschiedenen Zielen. Wahrscheinlich ist Punkt 5 für Pan von Kopf 1 nicht richtig eingestellt. Das muss neu gemessen werden.
- **Zweiter Fit** mit nachgestelltem Punkt 5 (Kopf 1 Pan 39168): Kopf 1 wird schlechter (Pan ca. 12°). Ursache: Pan-Wert der Deckenmitte ist identisch mit dem der linken Ecke (Punkt 3). Die Geometrie lässt das nicht zu. Die Messung für Kopf 1 ist also widersprüchlich, nicht das Modell.
- Die Pan-Skalierung von Kopf 1 (65 DMX/Grad) liegt weit unter dem Erwartungswert (ca. 121 DMX/Grad bei 540°). Auch das spricht gegen die aktuellen Messpunkte.
- **Entscheidung:** Die Deckenmitte bleibt draußen. Der Lichtkegel ist auf die kurze Distanz so breit, dass der Fleck dort keinen klaren Zielpunkt hat. Für die Kalibrierung zählen Punkte, auf die der Fleck klar trifft: TV-Wand, Tisch, Sofa.
- Die Unschärfe des Kegels ist auch eine gute Nachricht für die Show: Ein paar Zentimeter Fehler fallen kaum auf.
- **Dritter Fit** (Deckenmitte raus, Punkt „rechts neben TV“ rein, Höhe 2,50 m und Wandabstand 5,9 m fest, nur die Seitenposition frei):
  - Kopf 1 bei x ≈ 4,9 m (rechte Kopfwand), Pan 112 DMX pro Grad, Tilt 451 DMX pro Grad.
  - Kopf 2 bei x ≈ 0,1 m (linke Kopfwand), Pan 122 DMX pro Grad, Tilt 430 DMX pro Grad.
  - Größte Restfehler pro Achse, aus den Abweichungen in der Tabelle: Pan etwa 1,3°, Tilt bei Kopf 1 etwa 3°, bei Kopf 2 etwa 2°. Auf sechs Metern sind das rund 15 cm im Pan und 20 bis 30 cm im Tilt.
  - Für einen Lichtkegel, der ohnehin breit ist, ist das gut genug, um die Köpfe auf Zielpunkte zu richten. Feinere Werte bringen mit den Messungen von HA kaum noch etwas.
- Sofa-Mitte ist nicht erreichbar, beide Köpfe kommen dort nicht hin. Das bleibt vorerst offen. Der Tilt-Bereich nach unten könnte zu klein sein, oder das Sofa liegt außerhalb des Schwenkbereichs. Für den Fit reichen die fünf Punkte.
- Validierung: Zielpunkt Tisch und Zielpunkt links neben dem TV passen, ohne Nachjustieren.
- Justieren nur über `halte.py`, nicht über HA-Slider. HA sendet bei jeder Änderung seinen eigenen Stand und überschreibt damit unsere Positionen. HA sieht die Werte von `halte.py` nicht, die Endwerte stehen im Terminal (`-> Pan …, Tilt …`).
- **Achsenspiegelung:** Das Modell hat die x-Achse gespiegelt gegenüber dem Raum (Blick vom Sofa zum TV: rechts = −x). Die Messpunkte allein können das nicht unterscheiden. Die Web-App rechnet deshalb x → 5 − x um. Die Gleichungen in `ziel.py` bleiben unverändert. Beim nächsten Fit die Messpunkte im Raumkoordinatensystem prüfen.

Punkt 4 bestätigt die Tilt-Richtungen: Der Tisch liegt tiefer als die TV-Mitte. Kopf 1 steigt dafür von
28 auf 59, Kopf 2 fällt von 227 auf 196. Gegenläufig, wie erwartet.

Auffällig: Beide Köpfe sollen von Punkt 1 zu Punkt 2 nach oben schwenken, aber der Tilt-Wert wandert bei
Kopf 1 abwärts (7168 → 3840) und bei Kopf 2 aufwärts (58112 → 61952). Das deutet auf eine umgekehrte
Tilt-Achse bei einem der beiden Köpfe. Welche Richtung zu welchem Wert gehört, ist noch nicht gemessen;
Punkt 3 bestätigt das: Kopf 1 geht nach oben auf kleinere Tilt-Werte, Kopf 2 auf größere.
Pan ist bei beiden Köpfen symmetrisch um die Mitte: Kopf 1 links 153, Mitte 161, rechts 171;
Kopf 2 links 87, Mitte 97, rechts 105. Der Tilt-Wert der linken Ecke liegt bei Kopf 1 um 5 Schritte
unter der rechten. Das ist vermutlich die Geometrie der Montage, nicht ein Fehler. Pan wandert bei beiden Köpfen nur leicht
(Kopf 1: 161 → 171, Kopf 2: 97 → 105).

**Messung Motor speed (Kopf 1, Pan 0 → Maximum, Tilt Mitte):** Bei `motor_speed` 0 etwa 2,1 s für die
volle Strecke (gestoppt). Bei 255 erreicht er das Ziel in 4 s Hold nicht, also ist 255 das
**langsamste** Ergebnis. Skala: 0 = schnellstens, 255 = langsamsten. Für den Takt brauchen wir niedrige
Werte, die Feinabstimmung kommt in Phase 2. Gemessene Fahrzeiten (Pan 0 → Maximum): Speed 0 ca. 2,1 s, Speed 128 ca. 3,1 s, Speed 255 über 4 s.
Test: `lichtregie/dev/artnet_test.py`.

**Bewegungsgeschwindigkeit:** Ein Kopf braucht Zeit, um zu schwenken. Zielwechsel im Takt werden
darum geglättet (Rampe), und Sprünge laufen auf dem Beat, nicht dauernd.

## 4. Audio: Musik in Ereignisse übersetzen

- **Quelle:** Der Pi 5 hat keinen Line-In. Eingang ist ein USB-Audio-Adapter oder USB-Mikrofon
  (Frage 1). Ein Mikrofon hört auch den Raum; ein Line-In vom Verstärker oder TV ist sauberer.
- **Analyse** (numpy, kein Machine-Learning): FFT über 1024 Samples bei 44,1 kHz, daraus
  - Energie in Bass (≈ 40–150 Hz), Mitten, Höhen,
  - Onset-Erkennung (Anstieg der Energie gegen einen gleitenden Mittelwert) → Beat-Ereignis,
  - Tempo (BPM) aus dem Abstand der letzten Beats, mit Glättung.
- **Latenz:** Bild und Ton liegen um etwa 50–100 ms auseinander. Das lässt sich über einen
  Offset-Regler im Add-on kompensieren.
- **Rechenlast:** Gering. Der Nutzer achtet auf die Last des Pi (siehe Memory), deshalb
  bleibt die Analyse bewusst schlank.

## 5. Effekte (Köpfe, synchron)

Alle Effekte beschreiben, wohin T zeigt und wie die Köpfe zueinander stehen:

| Effekt | Beschreibung |
|---|---|
| **Konvergenz** | Beide auf einen Punkt T; T wandert auf einer Bahn (Kreis, Lissajous, Zufallssprünge auf dem Beat) |
| **Fächer** | Die Köpfe spreizen sich mit der Energie, schließen sich in ruhigen Passagen |
| **Spiegel** | Beide Köpfe spiegeln sich um die Raummitte |
| **Wechsel** | Abwechselnd auf jedem Beat auf die linke oder rechte Wand |
| **Scan** | Horizontale Linie über Wand oder Decke, Geschwindigkeit an BPM gekoppelt |
| **Beat-Blitz** | Farbwechsel und Strobe auf Bassschlag (mit Begrenzung, siehe Sicherheit) |
| **Ruhe** | Köpfe auf Ruheposition, dunkel oder leise Farbe |

Farben: aus dem Spektrum. Bass → rot/magenta, Mitten → grün, Höhen → blau/weiß. Helligkeit = Energie,
mit Attack und Release (schnell auf, langsam ab), damit es nicht flackert.

## 6. Laser (vorerst außen vor, später optional)

Der Laser wird in der ersten Version nicht angesteuert. Er bleibt bei den bestehenden HA-Automationen
bzw. bei der manuellen Steuerung. Falls er später dazukommt, dann nur über vorgefertigte Muster
(Presets) und nicht mit Zielpunkten im Raum.

- Muster (Form, Größe, Rotation) und Spiegelung folgen den Bändern und dem Tempo.
- **Verbotszonen:** Der Laser darf nie auf Kopfhöhe in Richtung Sofa, Fenster, Personen oder Spiegel
  zeigen. Die Zonen werden als Raumquader definiert. Der Laser bekommt nur Ziele an Decke oder
  Wand über Kopfhöhe. Das prüft das Add-on vor jedem Frame.

## 7. Lampen (RGB und LED-Streifen)

- Die Lampen laufen als **Stimmungsebene**, nicht im Beat. Zigbee oder WLAN-Lampen schaffen
  ein paar Updates pro Sekunde; das reicht für Farbverlauf und Helligkeit.
- Der LED-Streifen hinter dem TV ist das Ambilight, zwei **Yeelight**-Geräte
  (`light.wohnzimmer_1_ambilight`, `light.wohnzimmer_2_ambilight`, Bereich Wohnzimmer). Sie laufen
  über die Yeelight-Integration und werden über HA gesteuert, wie alle Lampen.
- **Steuerung über HA, auch für die Lampen:** Die Hersteller sind gemischt (Yeelight, Zigbee,
  Art-Net-Dimmer), daher gehen alle Lampen über HA-Services. Das reicht für Stimmung und Takt im
  Sekundenbereich. Der Beat-Takt bleibt bei den Köpfen, die direkt per Art-Net laufen.
- Option: Ambilight-Effekt am TV-Streifen, aus dem Farbmittel des Bildes. Das ist nicht Teil der
  ersten Version.

## 8. Modi

| Modus | Verhalten |
|---|---|
| **Aus** | nichts, alle Kanäle 0, bestehende Automationen wieder frei |
| **Ambient** | langsame Farbverläufe, Köpfe ruhig auf Positionen, kein Laser |
| **Party** | Musik-Effekte, Köpfe im Takt, Lampen im Beat-Takt |
| **Film** | Lampen gedimmt, Köpfe aus |
| **Auto** | startet, wenn Musik erkannt wird **und** Anwesenheit Wohnzimmer an ist; stoppt nach Stille (z. B. 5 Minuten) |

Auswahl über `select.lichtregie_modus` in HA, Schalter `switch.lichtregie_aktiv`, Ingress-Oberfläche
mit Live-Vorschau (Draufsicht des Raums mit Strahlen), Kalibrierungs-Assistent, Zustand.

## 9. Sicherheit

- **Laser:** Vorerst nicht angesteuert. Falls er später dazukommt, gilt die Regel: nichts unterhalb
  von etwa 2 m über dem Boden im Wohnbereich. Der Hersteller-Hinweis zur Laserklasse gilt.
- **Strobe:** Begrenzung auf höchstens etwa 3 Blitze pro Sekunde (Schutz vor photosensitiver
  Epilepsie). Ein Schalter in HA bricht den Strobe sofort ab.
- **Not-Aus:** Ein Taster in HA und ein Button im Dashboard setzen alle Show-Kanäle auf 0 und
  stoppen die Analyse.
- **Heartbeat:** Stürzt das Add-on ab, bekommen die Köpfe und der Laser keinen neuen Frame mehr.
  Die letzten Werte bleiben stehen. Beim Beenden sendet das Add-on daher einen Blackout-Frame,
  und ein Watchdog im Add-on setzt die Kanäle nach einigen Sekunden ohne Herzschlag zurück.
- **Rückfall auf HA:** Ist das Add-on aus, bleiben die bestehenden HA-Automationen die Steuerung.

## 10. Technik (Vorschlag)

- Python 3, aiohttp (wie hausakku_planer), numpy, sounddevice oder ALSA direkt, Art-Net per
  UDP-Socket.
- HA-Anbindung über den Supervisor-Proxy, wie `hausakku_planer/app/ha_client.py`.
- Ingress-UI mit einer Seite für Modi, Kalibrierung, Vorschau.
- Erst testen mit einem Mock-Node (UDP-Empfänger), dann mit echter Hardware.

## 11. Phasen

| Phase | Inhalt | Ergebnis |
|---|---|---|
| 0 | Fragen klären (siehe unten), Node- und Fixture-Daten | Kanalliste, Node-IP, Universe |
| 1 | Art-Net-Sender, Test mit echtem Node (Merge oder LTP?), Audio-Analyse mit Konsolenausgabe | Beat und Bänder kommen an, Köpfe bewegen sich |
| 2 | Raummodell und Kalibrierung, Konvergenz-Effekt | „Beide auf einen Punkt“ funktioniert |
| 3 | Effekte, Modi, Lampen (Laser später) | Party- und Ambient-Modus laufen |
| 4 | Ingress-UI mit Vorschau, Auto-Modus, Heartbeat und Not-Aus | Alltagstauglich |
| 5 (optional) | Kamera-Kalibrierung | Der Assistent kalibriert sich selbst |

## 12. Offene Fragen

1. **Audioquelle:** USB-Mikrofon im Raum, oder Line-In vom Verstärker oder TV (dann USB-Soundkarte nötig)?
2. **Art-Net-Nodes:** *Beantwortet.* IPs, Universe und Kanäle stehen in `configuration.yaml`
   (siehe Abschnitt 1). HA sendet nur bei Änderungen (`refresh_every: 0`).
3. **Moving Heads:** Pan und Tilt sind 16 Bit, also geklärt. Hersteller: Uking (Billigmarke, kein
   offizielles Handbuch gefunden). Offen: Modellnummer und DMX-Modus, damit wir die Funktion von
   `auto mode` und `config mode` kennen. Eine Websuche liefert nur Ableitungen von anderen Modellen,
   siehe [Finale-Kanalliste (9-Kanal-Uking)](https://finale3d.com/?p=1556708) und
   [Finale-Eintrag RGBW-Uking](https://finale3d.com/?p=512460). Dort: Pan 255 = 540°, Tilt 0 = −25°,
   255 = 205°. Die Belegung für unseren 16-Kanal-Modus ist damit nicht bestätigt.
4. **Lampen und Ambilight:** *Teilweise beantwortet.* Das Ambilight sind zwei Yeelight-Geräte und
   läuft über HA. Offen: Welche Entitäten sind die normalen RGB-Lampen im Wohnzimmer (die Deckenlampe
   mit dem lila Rand auf den Fotos)? Sie laufen ebenfalls über HA.
5. **Geometrie (beantwortet):** Raum etwa 6 m tief (TV-Wand bis Köpfe-Wand) und 5 m breit.
   Die beiden Köpfe hängen an der Wand gegenüber dem TV, etwa 5 m auseinander, auf **2,50 m Höhe**
   (Annahme: Montagehöhe, bitte bestätigen). Offen: genaue Position des Sofas (Abstand zur Köpfe-Wand).
6. **Ort im Repo:** `lichtregie/` im selben Repo, eigene Add-on-Version ab 0.1.0 – einverstanden?

---

## 13. Show ohne Audio (Stand, nur Köpfe)

Datenquelle ist Spotify über HA: Titel, Position, Länge, Lautstärke, und aus der Tempo-Datenbank BPM, Energie,
Valence, Tanzbarkeit, Lautheit. Kein Mikrofon, kein Audiostream.

**Ebenen**
1. **Takt:** Der Schlag wird an die Position im Lied gekoppelt (`song_position()` aus HA, Periode 60/BPM).
   Ohne Position (pausiert) läuft der Takt ab Startzeit weiter. **Umgesetzt.**
2. **Charakter:** Energie bestimmt den Wechselrhythmus (druckvoll: jeder Schlag, mittel: alle 2, ruhig: alle 4).
   Valence steuert die Farbe, Tanzbarkeit die Ausschlagsgröße, Lautheit die Helligkeit. **Teilweise umgesetzt**
   (Energie für den Wechsel).
3. **Struktur:** Intro (erste 8 Takte) und Ende (letzte 8 Takte) gehen in die Ruhepose, dazwischen der Takt.
   **Umgesetzt**, Phrasen von 8 Takten noch offen.

**Hardware-Grenzen** (gemessen): Bei Speed 0 fährt ein Kopf 540° in etwa 2,1 s. A und B liegen rund 25° auseinander,
Wechsel pro Schlag sind dort gut machbar. Strobe höchstens 3 Hz.

**Offen:** Phrasen-Zählung, Farbe nach Valence, Lampen über HA (langsamere Ebene), manuelle Modi in der Web-App.

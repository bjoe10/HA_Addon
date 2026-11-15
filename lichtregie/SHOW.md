# Lichtregie – Show-Design für die Moving Heads

Ziel: aus zwei Moving Heads, Laser und Lampen eine Show machen, die musikalisch wirkt und nicht nach
Zufallsgenerator aussieht. Grundlage sind die Song-Daten aus Spotify/HA und der Tempo-Datenbank; seit 0.3.0
kommt Live-Audio dazu (siehe „Stand der Umsetzung“).

Die Abschnitte 1–9 sind das Design mit den Messwerten: was gemessen ist, steht als **gemessen**, was
angenommen ist, als **Annahme**. Was davon gebaut ist, steht unter „Stand der Umsetzung“.

---

## 1. Was wir haben

### Die Köpfe (gemessen)

| Kanal | Verhalten | Folgen für die Show |
|---|---|---|
| Pan/Tilt 16 Bit | Pan ca. 540°, ca. 112–122 DMX pro Grad; Tilt ca. 150°, ca. 430–450 DMX pro Grad | feine, flüssige Bahnen möglich |
| Motor speed | 0 = schnell (540° in 2,1 s), 128 = 3,1 s, 255 = über 4 s | Show läuft mit 0 |
| Sprungzeit | **gemessen:** 10° ca. 0,5 s, 90° ca. 0,7 s – Anfahren und Abbremsen dominieren | höchstens ca. 1 Sprung/s; fließende Bahnen statt vieler kleiner Sprünge; Vorlauf 0,4 s |
| Farbe | Farbrad: weiß 0, rot 17, grün 22, blau 36, gelb 44, orange 54, eisblau 64, lila 73; Halbfarben 85–139; ab 140 Auto. **Mechanisch**: läuft durch die Zwischenfarben, weiter Sprung ca. 0,5 s | keine Mischfarben; ein weiter Wechsel dauert etwa einen Schlag, also im Dunkeln wechseln |
| Gobo | offen 0, Atom 13, Punkte-Ring 21, Punkte-Blume 27, grobe Löcher 34, Blasen 43, Swirl 50, Striche 57; Zittern je Muster in 3 Stufen ab 73 bis 126 | Muster als Textur, Zittern als Steigerung |
| Strobe | 0 und 255 = kein Blinken, 1–254 blinkt, je höher desto schneller, 200 „gut“ | Frequenz noch unbekannt |
| Dimmer | unter ca. 10 aus, ab 10 linear heller. Insgesamt **nicht sehr hell** | **das** Werkzeug für den Takt (siehe 3.1); Werte unter 10 vermeiden |

### Der Raum (gemessen, kalibriert)

- Raum ca. 5 m breit, 6 m tief, 2,5 m hoch. Köpfe in den beiden Ecken der Kopfwand, 2,5 m hoch, 5 m auseinander.
- TV-Wand 6 m entfernt, TV mittig (ca. x 1,9–3,1 m, Höhe 0,5–1,3 m).
- Jeder Punkt auf Boden, Wänden und Decke ist über das Modell ansteuerbar, Genauigkeit ca. 1–2° (10–20 cm auf 6 m).
- Sofa ist nicht erreichbar. Gut so, dort sitzen Menschen.
- Leute auf dem Sofa schauen zur TV-Wand, die Köpfe sind hinter ihnen. Sie werden also nicht geblendet,
  solange die Spots auf TV-Wand, Decke und vorderem Boden liegen.

### Die Musikdaten (gemessen)

| Quelle | Daten | Genauigkeit |
|---|---|---|
| HA (Spotify) | Titel, Interpret, Länge, Position, Play/Pause, Lautstärke, Playlist | Position ±2–5 s, Wechsel nach 2–4 s erkannt |
| FreqBlog | BPM, Taktart, Tonart (Dur/Moll), Energie, Tanzbarkeit, Valence, Lautheit, Genre | BPM gut, Rest grobe Einordnung |

**Was fehlt:** wo der erste Schlag liegt (Phase), wo Drops und Breaks sind, wie es klingt.

---

## 2. Die wichtigsten Abhängigkeiten

Diese Punkte entscheiden, ob die Show gut aussieht. Sie stehen hier vor den Effekten, weil die Effekte sich danach richten müssen.

1. **Ohne Nebel sieht man keine Strahlen, nur Flecken.** Die Show spielt sich auf Wänden, Boden und Decke ab.
   Effekte, die von sich kreuzenden Strahlen leben, wirken ohne Nebel nicht. Ein kleiner Hazer würde
   die Wirkung vervielfachen (Frage an dich).
2. **Phase unbekannt.** Harte Akzente (Blitz, Puls) wirken falsch, wenn sie neben dem Schlag liegen.
   Gleichmäßige Bewegungen im Tempo (ein Kreis pro Takt) wirken dagegen immer „im Takt“, auch ohne Phase.
   Folge: ohne Phasen-Abgleich nur weiche Effekte; Pulse und Strobe erst nach optionalem Tap.
3. **Mechanik ist langsam, Dimmer ist schnell.** Pan/Tilt brauchen 0,1–0,3 s für kurze Wege, Farb- und Goborad
   brauchen Zeit und laufen dabei über die Nachbarfarben/-muster (**Annahme**, muss gemessen werden).
   Der Dimmer reagiert sofort. Folge:
   - Takt-Akzente kommen über den Dimmer, nicht über Bewegung.
   - Bewegungen werden um ihre Laufzeit **vorgezogen**, damit sie auf dem Schlag ankommen.
   - Farb- und Gobowechsel passieren im Dunkeln (Dimmer kurz auf 0) oder zwischen Nachbarn auf dem Rad.
4. **Position nur ±2–5 s genau.** Phrasen (8 Takte) lassen sich zählen, liegen aber ggf. einen Takt daneben.
   Folge: Szenenwechsel mit 1 Takt Übergang, nicht als harter Schnitt.
5. **Die Köpfe sind lichtschwach.** Folgen:
   - Der Raum muss dunkel sein. Wenn später die Lampen dazukommen, laufen sie während der Show stark gedimmt.
   - Pulse arbeiten mit vollem Ausschlag (z. B. 255 auf dem Schlag, 60–100 dazwischen), sonst sieht man sie nicht.
   - Nahe Flächen sind deutlich heller als ferne: ein Spot auf der Decke in 3 m ist etwa viermal so hell wie auf
     der TV-Wand in 6 m. Gobo-Muster schlucken zusätzlich Licht, deshalb Muster bevorzugt auf Decke und
     vorderen Boden, offene Spots auf die TV-Wand.
6. **Strobe fest auf 200**, höchstens 1 Takt am Stück, in der Web-App abschaltbar.
7. **Köpfe hängen an Steckdosen** (`switch.moving_head_1/2`). Vor der Show einschalten und Bootzeit abwarten
   (die alte Automation wartet 13 s). Nach der Show nach einer Ruhezeit wieder ausschalten.
8. **HA darf nicht dazwischenfunken.** Die alten Party-Automationen bleiben aus, die HA-Regler werden während
   der Show nicht benutzt.

---

## 3. Bausteine

Eine Szene besteht aus fünf Bausteinen, die unabhängig voneinander kombiniert werden.

### 3.1 Dimmer-Muster (der Takt)

| Muster | Verhalten | wann |
|---|---|---|
| Atmen | sanft auf und ab über 2 Takte | ruhig, Intro, Outro |
| Halbzeit-Puls | Puls auf Schlag 1 und 3 | mittel |
| Puls | jeder Schlag hell, dann abklingen auf 30–60 % | druckvoll |
| Gegenpuls | Kopf 1 auf den Schlag, Kopf 2 dazwischen | druckvoll, Abwechslung |
| Blackout-Lücke | 1 Schlag dunkel vor einer neuen Phrase | Übergänge, versteckt Radwechsel |

Pulse brauchen die Phase. Ohne Tap-Abgleich nur Atmen.

### 3.2 Bewegungen (wohin die Spots laufen)

Alle Bahnen sind Wege auf den Raumflächen, ausgerechnet über das Modell. Eine Bahn läuft immer in ganzen
Takten, damit sie im Tempo wirkt.

| Bahn | Fläche | Beschreibung | Takte pro Durchlauf |
|---|---|---|---|
| Fokus | beliebig | beide Spots auf einem Punkt, ruhig | – |
| Pendel | TV-Wand | Spot schwingt links–rechts, z 1,6–2,2 m | 1 Schwung pro Schlag oder pro Takt |
| Kreis | TV-Wand oder Decke | Kreis um einen Mittelpunkt, Radius nach Energie | 1 oder 2 |
| Acht | TV-Wand | liegende Acht, fließend | 2 oder 4 |
| Boden-Lauf | Boden vor dem TV | Spots wandern über den vorderen Boden | 4 |
| Ecken-Sprung | TV-Wand | Sprünge zwischen Ecken, Mitte und TV-Rand | 1 Sprung pro Schlag oder Takt |
| Wand-Lauf | alle Wände | Spots laufen einmal um den Raum | 4 oder 8 |
| Sternhimmel | Decke | kleiner, langsamer Kreis mit Punkte-Gobo | 8 |

### 3.3 Verhältnis der beiden Köpfe

| Verhältnis | Wirkung |
|---|---|
| Gleich | beide Spots auf derselben Bahn, wirkt wie ein großer Spot |
| Spiegel | Bahn an der Raummitte gespiegelt, Spots treffen sich in der Mitte |
| Gegenläufig | gleiche Bahn, halber Durchlauf versetzt (z. B. zwei Spots jagen sich im Kreis) |
| Versetzt | Kopf 2 einen halben Schlag später, wirkt wie eine Welle |
| Frage-Antwort | Kopf 1 bewegt sich, Kopf 2 steht, dann umgekehrt |
| Kontrast | gleiche Bahn, verschiedene Farben |

### 3.4 Farbe

Jeder Titel bekommt eine **Palette aus 2–3 Nachbarfarben auf dem Rad**. Nachbarn, weil der Wechsel dann kurz
ist und nicht über fremde Farben läuft.

- **Tonart bestimmt die Grundfarbe.** Dieselbe Tonart bekommt immer dieselbe Farbe, so hat jedes Lied seinen
  Charakter, und Lieder in derselben Tonart passen zusammen.
- **Dur → warm** (rot, orange, gelb, weiß), **Moll → kühl** (blau, eisblau, lila, grün).
- **Valence** verschiebt: niedrig → dunklere Nachbarn (blau, lila), hoch → hellere (gelb, weiß).
- **Halbfarben** (z. B. eisblau/lila) als Akzent auf dem Höhepunkt einer Phrase.
- Farbwechsel nur auf Phrasengrenzen, im Blackout-Schlag.

### 3.5 Gobo und Strobe

- Gobo offen für klare Spots auf der TV-Wand.
- Punkte-Ring oder Punkte-Blume an der Decke („Sternhimmel“), Swirl und Blasen für fließende Teile.
- Zittern als Steigerung: langsam bei mittlerer Energie, schnell nur auf dem Höhepunkt.
- Strobe nur bei hoher Energie und Dance/Electronic, höchstens 1 Takt am Anfang einer Phrase,
  höchstens einmal pro 32 Takte, Frequenz begrenzt.

---

## 4. Wie die Musik die Show steuert

### Song-Profil (beim Titelwechsel berechnet)

| Daten | Steuert |
|---|---|
| BPM | Uhr für alles: Schläge, Takte, Phrasen |
| Energie | Intensität: Dimmer-Muster, Bewegungsgröße, Tempo der Bahnen, Zittern, Strobe erlaubt |
| Tanzbarkeit | hoch: Effekte auf dem Schlag (Sprünge, Pulse); niedrig: fließende Bahnen (Acht, Kreis) |
| Tonart + Dur/Moll | Farbpalette |
| Valence | Helligkeit der Palette |
| Lautheit | Grundhelligkeit, damit leise Stücke nicht überstrahlen |
| Länge + Position | Intro, Hauptteil, Outro, Phrasengrenzen |

### Song-Thema (jedes Lied wirkt wie eigens programmiert)

Jedes Lied bekommt beim ersten Abspielen ein festes Thema. Es wird aus der Spotify-Track-ID abgeleitet,
deshalb sieht dasselbe Lied **jedes Mal gleich** aus, und verschiedene Lieder sehen verschieden aus.

| Teil des Themas | Woraus | Wirkung |
|---|---|---|
| Grundfarbe | Tonart, Dur/Moll | die Farbe, die das Lied trägt |
| Akzentfarbe | Nachbar der Grundfarbe auf dem Rad, nach Valence | kommt auf Höhepunkten und Phrasenanfängen |
| Signatur-Gobo | aus den 8 Mustern, nach Energie gewichtet | das Muster, das immer wieder auftaucht |
| Motiv | kurze Figur über 2 Takte, z. B. beide Spots auf TV-Mitte, Akzentfarbe, Gobo | kehrt am Anfang jeder Phrase wieder, wie ein Erkennungszeichen |
| Szenen-Satz | 3–4 Szenen aus dem Pool der Stufe | wiederholen sich in fester Folge (A B A C A B …), wie Strophe und Refrain |
| Refrain-Szene | die stärkste Szene des Satzes | kommt bei den Höhepunkten, immer dieselbe |

- Lieder in derselben Tonart teilen die Grundfarbe, unterscheiden sich aber in Gobo, Motiv und Szenen.
- Das Thema wird pro Track gespeichert. In der Web-App gibt es später „Thema neu würfeln“ und
  „Thema behalten“, damit du ein Lied umgestalten oder ein gelungenes festhalten kannst.

### Intensitätsstufen

| Stufe | Energie | Dimmer | Bewegung | Gobo | Strobe |
|---|---|---|---|---|---|
| ruhig | unter 0,4 | Atmen | Acht, Sternhimmel, Fokus, langsam | Muster, kein Zittern | nie |
| mittel | 0,4–0,6 | Halbzeit-Puls | Kreis, Pendel pro Takt, Wand-Lauf | Zittern langsam | nie |
| druckvoll | über 0,6 | Puls, Gegenpuls | Pendel pro Schlag, Ecken-Sprung, Kreis pro Takt | Zittern mittel/schnell | Höhepunkt |

---

## 5. Ablauf eines Liedes

```
Titelwechsel ─▶ Blackout 1 Schlag ─▶ Intro ─▶ Hauptteil (Phrasen) ─▶ Outro ─▶ Titelwechsel …
```

- **Intro** (erste 8–16 Takte): ruhige Szene in der Palettenfarbe, Atmen, Sternhimmel oder Fokus.
- **Hauptteil:** alle 8 Takte (bei langen Liedern 16) eine neue Szene aus dem Pool der Stufe.
  Regeln: nie zweimal dieselbe Szene, Fläche wechseln (TV-Wand → Decke → Boden), alle 32 Takte ein Höhepunkt
  bei druckvollen Liedern.
- **Outro** (ab 0.6.1 nur die letzten 2 Takte, bis 60 % gedimmt; bis 12 Takte vorher, wenn das Audio ein
  Auslaufen ohne Kick zeigt): Spots laufen zu einem gemeinsamen Punkt, werden langsamer. Setzt das nächste
  Lied gleich voll ein, entfällt das ruhige Intro.
- **Übergang:** Blackout, Rad auf die neue Grundfarbe, neues Intro.
- **Pause** (2 s kein Ton am Empfänger): Spots treffen sich über dem TV und atmen in der Grundfarbe des Liedes.
  **Warten** (Party an, keine Musik): Sternhimmel an der Decke, Kreise, Farbwechsel alle 24 s. Details unter
  „Party-Modus“ im Abschnitt „Stand der Umsetzung“.

---

## 6. Grenzen

Sperrzonen (TV, Fenster, Stehbereich) gibt es nicht, alle erreichbaren Flächen sind frei.
Das Sofa ist ohnehin nicht erreichbar.

| Grenze | Regel |
|---|---|
| Strobe | Obergrenze ca. 3 Blitze/s, höchstens 1 Takt am Stück |

---

## 7. Aufbau der Software

```
Titel (HA) ─▶ Tempo (FreqBlog) ─▶ Song-Thema ─▶ Show-Regeln ─▶ Köpfe/Laser per Art-Net (40 Bilder/s)
                    Live-Audio ─▶ Schlagzählung ─┘          └▶ Lampen über HA (selten)
```

| Datei in `app/` | Aufgabe |
|---|---|
| `server.py` | Web-Server, Schnittstelle der Oberfläche, Art-Net-Sender, Start |
| `party.py` | Party-Modus: Hauptschalter, Automatik, Geräte ein/aus |
| `engine.py` | Show-Motor: Titel-Überwachung, Show-Schleife, Thema je Lied, Audio-Warnung |
| `show.py` | Show-Regeln als reine Funktionen der Taktposition (ohne Raum testbar) |
| `audio.py`, `beatcount.py` | Audioanalyse (Takt, Break, Drop, Klangwechsel) und Schlagzählung |
| `heads.py`, `laser.py`, `lamps.py` | Geräte: Zustand, Grenzen, Anschub/Vorsteuerung, HA-Lampen |
| `geometry.py`, `artnet.py` | Kalibriermodell Raumpunkt → Pan/Tilt, ArtDMX-Pakete |
| `ha.py`, `tempo.py`, `config.py`, `settings.py` | HA-Zugriff, FreqBlog, Add-on-Optionen, Schalter der Oberfläche |
| `web/` | Oberfläche (HTML, CSS, JavaScript) |

- **Taktposition** = Liedposition × BPM / 60, mit Audio aus der eigenen Schlagzählung.
- **Vorziehen der Bewegung** um die Laufzeit des Kopfes, damit die Spots auf dem Schlag ankommen.
- **Radwechsel:** Farbe/Gobo nur im Dunkeln oder zu Nachbarn.
- **Tests:** `dev/test_all.sh` (Konfiguration, Audioanalyse, Schlagzählung, Pipe mit Liedwechseln, Rauchtest von
  Motor, Party und Web).

---

## 8. Was vorher gemessen werden muss

| Messung | Wozu | Wie |
|---|---|---|
| ~~Farbrad~~ | **gemessen:** läuft durch die Zwischenfarben, weiter Sprung ca. 0,5 s | – |
| ~~Goborad~~ | **gemessen:** wie das Farbrad, läuft durch die Zwischenmuster, weiter Sprung ca. 0,5 s | – |
| ~~Strobe-Frequenz~~ | **entschieden:** fester Wert 200, keine Messung | – |
| ~~Dimmer~~ | **gemessen:** ab ca. 10 linear, unter 10 aus; Köpfe eher lichtschwach | – |
| Bahn-Glätte bei Motor speed 0, 30, 60 | flüssige Kreise | Kreis-Test aus der Web-App |
| Gobo-Schärfe auf Decke und TV-Wand | wo Muster schön aussehen | Muster auf beide Flächen richten |
| Bootzeit nach dem Einschalten | Start der Show | Steckdose an, Zeit bis zur Reaktion |
| Erreichbarkeit pro Kopf | Bahnen planen | Ecken und Kanten aus der Web-App antippen |

---

## 9. Entscheidungen

1. **Nebel:** kommt bei Bedarf, von Hand. In der Web-App gibt es einen Schalter „Nebel an“. Ist er an,
   bevorzugt der Szenen-Planer Strahl-Effekte (Kreuzen, Fächer, Spiegel); ist er aus, Flecken-Effekte.
2. **Strobe:** gehört zur Show. Die Menge stellt ein Regler in der Oberfläche ein (0–200 %, Standard 100 %),
   höchstens 1 Takt am Stück. Ein Schalter schaltet ihn ganz ab.
3. **Sperrzonen:** keine.
4. **Automatischer Start:** über den Party-Modus (siehe „Stand der Umsetzung“).
5. Offen: Ruhezeiten (z. B. ab 22 Uhr nur ruhige Stufe).

---

## Stand der Umsetzung (0.8.11)

**Show-Regeln** (`app/show.py`, reine Funktionen der Taktposition):
- Song-Thema aus der Track-ID: Grund- und Akzentfarbe aus der Tonart, zwei Gobos, Motiv-Punkt, 5 Szenen
  (mind. 2× Boden) in fester Folge, Refrain-Szene, Laser-Thema, Lampen-Rhythmus, Laser-Rolle.
- Szenen aus Bausteinen: 15 Formen (Kreis, Acht, Pendel waagerecht/senkrecht, Diagonale, Spirale, Welle,
  Zickzack, Zufallsflug, Stern, Quadrat, Sprungpunkte, Wand–Boden, Wandlauf, Fokus) auf Wand, Boden, Decke;
  8 Kopf-Verhältnisse; Dimmer-Muster; Farbverhalten Grund/Akzent/getrennt/Wechsel; Richtungswechsel alle
  2–4 Schläge. Testlauf über 360 Lieder: 1175 verschiedene Kombinationen, Wand 44 %, Boden 42 %, Decke 14 %.
- Ablauf: Intro (entfällt, wenn das Lied voll einsetzt), Motiv am Phrasenanfang, Szenen, Aufbau, jede
  4. Phrase Höhepunkt (Refrain, Gobo-Zittern, Strobe), Atempause, Outro in den letzten 2 Takten.
- Dunkler Schlag vor der Phrase, wenn Farb- oder Goborad wechseln muss; 0,6 s dunkel beim Liedwechsel.

**Mechanik** (`app/heads.py`): Bewegung 0,4 s vorgezogen; Mindestdauer je Bahn; Anschub (bei Sprüngen ab ca.
4° für 0,12 s das 2,5-fache Ziel) und Vorsteuerung (Ziel um Geschwindigkeit × 0,45 s voraus).

**Live-Audio** (`app/audio.py`, ab 0.3.0): AirPlay-Empfänger „Lichtregie“ im Add-on, in Music Assistant mit dem
Phantom gruppiert. Seit 0.8.7 startet die Lichtregie shairport-sync selbst und liest den Ton über stdout
(S16_LE, 44,1 kHz, stereo); endet shairport-sync, startet sie es nach 3 s neu. Gemessen am Gerät: Audio-Versatz
**80 ms** (Licht 80 ms vor der analysierten Phase), danach sitzen die Blitze auf dem Kick. Mit eingerastetem Takt:
Puls durch Abdunkeln kurz vor dem Schlag. Bildrate der Show am Pi 39,4/s (Soll 40), Last ca. 0,5 % CPU.
Kein Ton, während Spotify über 15 s spielt: Warnung in der Oberfläche und HA-Benachrichtigung.

**Takt- und Phrasen-Sync** (`app/beatcount.py`, ab 0.6.0): Mit eingerastetem Audio zählt die Lichtregie die
Schläge selbst (Phase aus der Analyse), HA liefert nur die Grobposition. Anker: Drop → nächste Phrasengrenze
(±12 Schläge), erkannter Klangwechsel → Phrasengrenze, wenn höchstens 3 Schläge daneben. Spulen (Sprung der
Liedposition über 5 s) setzt die Zählung sofort neu auf. Die „1“ im Takt kommt seit 0.8.13 aus dem Audio:
Klangwechsel je Schlag, über mehrere Takte auf die vier Positionen summiert; die deutlich stärkste wird zur „1“
(Takt-Anker). Danach verschieben Drop und Phrasenwechsel nur um ganze Takte; eine Korrektur von Hand hat Vorrang. Läuft die Audio-Zählung dauerhaft gegen die HA-Position (zwei Korrekturen in
dieselbe Richtung innerhalb von 60 s), zählt das Lied ab dann nach HA (seit 0.8.11). Synthetischer Test (`dev/test_beatcount.py`, HA
5 Schläge daneben): nach dem Drop Restfehler unter 0,1 Schlag.

**Lampen** (`app/lamps.py`): Die Ambilights wechseln seit 0.8.12 hart auf dem Schlag, im eingestellten
Rhythmus (Standard jeder Takt, „nach Lied“ = 8 oder 16 Takte; schneller geht nicht, die Yeelights nehmen nur ca.
60 Befehle pro Minute je Lampe an); nur geänderte Werte, Budget je Gruppe; um den Vorlauf
vorgezogen (Standard 0,8 s), Lampen-Schleife alle 20 ms. Grund- und Akzentfarbe
laufen über HA; Schrank 1 (links vom TV) und Schrank 2 (rechts) wechseln sich je Takt bei 100 % und 20 % ab,
die Ambilights durchlaufen Grund-, Akzent- und Komplementärfarbe. Der Ausgangszustand wird gesichert und nach
der Party wiederhergestellt.

**Laser** (`app/laser.py`): Rolle je Lied aus / nur Höhepunkte / jede zweite Phrase / durchgehend (Anteil an
der Liedzeit ca. 0 / 28 / 58 / 100 %). Ruhepunkt hoch/runter 76 (über dem TV), Bahnen nur zwischen 66 und 86.

**Party-Modus** (`app/party.py`, ab 0.8.0): Hauptschalter. An: Geräte einschalten (Köpfe, Laser, weitere
Steckdosen), Raum abdunkeln, Show starten. Aus: Köpfe fahren in die Parkposition (Pan 0, Tilt 0, damit beide
gleich hängen), nach 3,5 s gehen die Steckdosen aus. Automatik: an, sobald 3 s Ton am Empfänger ankommt; aus nach
`party_aus_min` (Standard 15) Minuten ohne Musik. Ein Stopp von Hand sperrt die Automatik, bis eine Minute Ruhe
war. Der Stand bleibt über Neustarts erhalten (`party.json`). „Thema neu würfeln“ merkt die Variante je Lied.

**Ruhe-Animationen** (`show.idle_frame`, Schleife in `engine.idle_loop`, ab 0.8.10): *Warten* (Party an, keine
Musik): Sternhimmel an der Decke, zwei gegenläufige Kreise (40 s pro Runde), Gobo Punkte-Ring, Atmen, Farbwechsel
alle 24 s im Dunkeln, Laser aus. *Pause* (2 s kein Ton): beide Spots über dem TV, pendeln leicht und atmen in
der Grundfarbe, Laser aus. Seit 0.8.12 läuft die Show mit Audio nur bei Ton: nach 10 s ohne Ton geht sie aus
(Warten), mit Ton startet sie sofort wieder, auch wenn HA noch „pausiert“ meldet.

**Noch offen:** Bootzeit der Köpfe nach dem Einschalten messen (sie beeinflusst, wann der Sternhimmel sichtbar
wird); Tanzbarkeit und Lautheit aus FreqBlog noch ungenutzt. Nach jedem Update muss „Party modus“ in Spotify neu
gewählt werden, sonst nimmt Music Assistant den Empfänger nicht wieder auf. Eine automatische Lösung über die
MA-API ist möglich, aber nicht umgesetzt.

## Laser (gemessen)

- **Modus (Kanal 23):** 0 = aus, 70 = Handbetrieb (Form nach Kanal „Form“), darüber Auto-Programme (nicht genutzt).
- **Form (Kanal 24), Startwerte:** 0 Quadrat, 8 Kreis, 13 senkrechter Strich, 17 waagerechter Strich,
  21 Diagonale (links oben → rechts unten), 27 Halbkreis unten, 34 Halbkreis links, 37 Dreieck, 43 V-Form,
  48 zwei senkrechte Striche, 52 zwei waagerechte Striche, 59 senkrechter Strich mit Lücke,
  64 waagerechter Strich mit Lücke, 67 Welle, 73 invertierte Welle, 79 Musiknote, 82 Kreis rechts oben,
  87 Tannenbaum, 92 Zahl 3, 96 „<“, 102 Stern, 108 senkrechte Welle, 113 Zahl 2, 116 Zahl 1, 122 Herz,
  128 Punkte in den Ecken, 132 Apfel, 136 gestrichelter Kreis, 142 zwei Kreise, 148 Doppelkreis,
  152 Fluxkompensator, 156 Plus, 162 Kreis mit Quadrat, 167 Doppeldreieck, 172 Striche-Swirl,
  176 drei Striche im Dreieck, 181 drei versetzte senkrechte Striche, 187 Fünfeck, 191 Fadenkreuz,
  196 D-Pad, 201 Pfeil nach oben, 207 Unendlich, 212 Wurfstern, 216 seltsames Dreieck,
  222 Quadrat auf der Spitze, 226 Dreieck mit Pfeil, 231 Sims-Kristall, 238 Fliege.
- Die Formen liegen ohne Rotation auf der Seite; aufrecht bei Rotation 93 (siehe unten).
- **Farbe (Kanal 31), Startwerte:** 0 mehrfarbig, 21 eisblau+lila, 30 eisblau+grün, 35 andere Farbverteilung,
  47 eisblau+grün+rot, 57 grün+rot+lila, 64 eisblau, 75 blau, 93 grün, 112 rot, 121 lila, darüber Auto-Programme.
  Zuordnung zu den Kopffarben: eisblau→64, blau→75, grün→93, rot→112, lila→121, gelb→grün, orange→rot,
  weiß→mehrfarbig; Mischungen für Höhepunkt und Drop.
- **Rotation (Kanal 25):** 0–125 fester Winkel, eine ganze Drehung im Uhrzeigersinn (ca. 2,9° pro Schritt;
  33 ≈ aufrecht), darüber Auto-Programme. Drehung im Takt deshalb selbst über den Winkel steuern.
- **Größe (Kanal 30):** 0 = am größten, 62 = am kleinsten, darüber Auto-Programme. Puls auf dem Schlag möglich.
- **Hoch/runter (Kanal 28):** 42 = ganz unten, 86 = ganz oben (gewählt, damit das Muster sichtbar bleibt);
  als Schutzgrenze eingestellt.
- **Links/rechts (Kanal 29):** 39 = ganz links, 90 = ganz rechts; als Schutzgrenze eingestellt.
- **Spiegel waagerecht (Kanal 26):** 0–125 ein voller Zyklus „Münzdrehung“ um die senkrechte Achse
  (zusammenziehen, gespiegelt, zurück). Im Takt animierbar wie die Rotation.
- **Spiegel senkrecht (Kanal 27):** dasselbe um die waagerechte Achse (Kippen), 0–125 ein voller Zyklus.
- **Punkte (Kanal 32):** 0–121 Punktgeschwindigkeit (0 schnell, 121 langsam), 129–255 gestrichelt
  (129 schnell, 255 langsam).
- **Aufrecht:** Die Symbole stehen bei Rotation 93 richtig (Spiegel beide 0). Modus 65 wirkt ebenfalls als
  Handbetrieb.
- Countdown „3, 2, 1“: Formen 92, 113, 116 in den letzten drei Schlägen vor einem Höhepunkt (in der Show).

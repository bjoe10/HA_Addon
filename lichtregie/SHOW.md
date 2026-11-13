# Lichtregie – Show-Design für die Moving Heads

Ziel: aus zwei Moving Heads, ohne Audio, nur mit den Song-Daten aus Spotify/HA und der Tempo-Datenbank,
eine Show machen, die musikalisch wirkt und nicht nach Zufallsgenerator aussieht.

Status: Entwurf. Was gemessen ist, steht als **gemessen**, was angenommen ist, als **Annahme**.

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
- **Outro** (letzte 8 Takte): Spots laufen zu einem gemeinsamen Punkt (TV-Mitte oben), werden langsamer, Atmen.
- **Übergang:** Blackout, Rad auf die neue Grundfarbe, neues Intro.
- **Pause:** Spots bleiben stehen und atmen leise. Nach einigen Minuten Pause ausblenden.

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
Song-Profil ──▶ Szenen-Planer ──▶ Effekt-Generatoren ──▶ Regeln ──▶ Art-Net (40 Bilder/s)
 (pro Titel)     (pro Phrase)      (pro Bild, je Kopf)     (Radwechsel, Strobe-Grenze, Pan-Kurzweg)
```

- **Effekte als reine Funktionen** der Taktposition (z. B. „Schlag 37,25“) und ihrer Parameter.
  Damit lassen sie sich ohne Raum testen und in der Web-App als **Vorschau** zeichnen: die Perspektive
  haben wir schon, die Spots lassen sich darauf live anzeigen.
- **Taktposition** = Liedposition × BPM / 60 + Phasen-Versatz (Tap optional).
- **Vorziehen der Bewegung** um die Laufzeit des Kopfes, damit die Spots auf dem Schlag ankommen.
- **Radwechsel-Planer:** Farbe/Gobo nur im Dunkeln oder zu Nachbarn, höchstens 1 Wechsel pro Takt.
- **Alles einstellbar:** Energie-Schwellen, Master-Intensität, Strobe an/aus, Phrasenlänge, Vorlauf.

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
2. **Strobe:** gehört zur Show, immer mit dem festen Wert 200, höchstens 1 Takt am Stück. Schalter in der Web-App zum Abschalten.
3. **Sperrzonen:** keine.
4. **Automatischer Start:** kommt ganz zum Schluss.
5. Offen: Ruhezeiten (z. B. ab 22 Uhr nur ruhige Stufe).

---

## Stand der Umsetzung

**Effekt-Motor, erste Fassung** (`dev/show.py`, eingebunden in `dev/webapp.py`):
- Song-Thema aus der Track-ID: Grund- und Akzentfarbe aus der Tonart, Signatur-Gobo, Motiv-Punkt, 3 Szenen in
  fester Folge, Refrain-Szene.
- Ablauf: Intro (1 Phrase, Sternhimmel), Hauptteil mit Motiv am Phrasenanfang, jede 4. Phrase Höhepunkt
  (Refrain, Gobo-Zittern, bei druckvoll Strobe im ersten Takt), Outro (Fokus, ausblenden).
- Dunkler Schlag vor der Phrase, wenn Farb- oder Goborad wechseln muss.
- 9 Bahnen, 6 Kopf-Verhältnisse (inkl. Kreuz für Nebel), 4 Dimmer-Muster.
- Bewegung 0,4 s vorgezogen, Takt an die Liedposition gekoppelt.
- Mindestdauer je Bahn (Sprünge höchstens ca. 1/s), bei schnellen Liedern verdoppelt.
- **Anschub:** bei Sprüngen ab ca. 4° für 0,12 s das 2,5-fache Ziel vorgeben, dann das echte
  (getestet: schneller, leichtes Nachwackeln). In der Web-App abschaltbar.
- Web-App: Schalter Strobe und Nebel, Szenen-Anzeige, Live-Vorschau der Spots im Raumbild.

**Zweite Fassung (Abwechslung):** Szenen werden aus Bausteinen erzeugt statt aus festen Listen:
15 Formen (Kreis, Acht, Pendel waagerecht/senkrecht, Diagonale, Spirale, Welle, Zickzack, Zufallsflug,
Stern, Quadrat, Sprungpunkte, Wand–Boden, Wandlauf, Fokus) auf Wand, Boden, Decke, mit zufälliger Lage
und Größe; 8 Kopf-Verhältnisse (neu: folgen, Kanon); 9 Dimmer-Muster (neu: Doppelpuls, Offbeat, Wechsel,
Blinken); Farbverhalten Grund/Akzent/getrennt/Wechsel pro Takt/Halbfarbe; Richtungswechsel alle 2–4 Schläge.
Pro Lied 5 Szenen (mind. 2× Boden), Variation in der zweiten Phrasenhälfte, Aufbau vor dem Höhepunkt,
Atempause danach. Testlauf über 360 Lieder: 1175 verschiedene Kombinationen, Wand 44 %, Boden 42 %, Decke 14 %.

**Noch offen:** Phasen-Abgleich (Tap/Versatz-Regler), „Thema neu würfeln/behalten“, Feinabstimmung der Bahnen
nach Sichtung, Tanzbarkeit und Lautheit noch ungenutzt.

## 10. Reihenfolge der Umsetzung

1. Messungen aus Abschnitt 8 (Rad, Strobe, Dimmer, Glätte).
2. Effekt-Motor mit Taktposition, Vorlauf und Dimmer-Mustern; Vorschau in der Web-App.
3. Bahnen und Kopf-Verhältnisse als Bibliothek.
4. Song-Profil, Palette und Szenen-Planer mit Phrasen.
5. Radwechsel-Planer, Strobe-Grenze.
6. Automatischer Start/Stopp, Steckdosen, Pausen.
7. Umzug als Add-on auf den Pi.

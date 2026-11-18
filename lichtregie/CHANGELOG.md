# Changelog

## 0.9.18

- **LED-Streifen: Blinder und Flash getrennt einstellbar** (Feinabstimmung → Lampen), je mit Dauer in Schlägen:
  Blinder aus / bei Drop und Höhepunkt / zusätzlich bei jedem Phrasenwechsel (Standard, 1 Schlag); Flash auf der
  „1“ aus (Standard) / nur in Höhepunkt und Drop / jeder Takt (½ Schlag).
- **Streifen nicht überfahren:** Zwischen zwei Befehlen liegen mindestens 0,4 s; schneller verschluckte der
  Streifen Befehle. Gemessen dauert ein Befehl über HA und Bluetooth ca. 0,36 s, der Vorlauf steht deshalb jetzt
  auf 0,35 s (bisher 0,2 s).
- Texte nachgezogen: Beschreibung der Option „LED-Streifen“ (gedimmte Farbe, weiße Blitze) und Kurzbeschreibung des
  Add-ons (Ton, Titel und Position über AirPlay statt Spotify über HA). Das Log nennt beim Start die LED-Streifen.

## 0.9.17

- **LED-Streifen (neu, Option „LED-Streifen“):** Schnelle Lichter ohne Befehlsgrenze, z. B. der Govee-Streifen
  hinter dem TV (Bluetooth). Grundzustand: die Farbe des Liedes, stark gedimmt (5 %, auf der Show-Seite
  einstellbar), bei Höhepunkt und Drop die Akzentfarbe, im Break aus. Dazu weiße Blitze in voller Helligkeit:
  „Blinder“ (ein Schlag weiß, wenn Drop oder Höhepunkt einsetzen), „Blinder + Takt“ (zusätzlich ein kurzer Blitz
  auf jeder „1“ während Höhepunkt und Drop) oder „nur Farbe“ (Feinabstimmung). Eigener Vorlauf unter Einrichten,
  der Lampen-Test lässt ihn auf jedem Schlag weiß blitzen. Nach der Party kommt sein alter Zustand zurück.
- **Schlaganzeige im Takt:** Die vier Punkte auf der Startseite lasen den Schlag aus dem Szenentext und sprangen
  nur bei jeder Abfrage (alle 200 ms plus Laufzeit über HA). Bei 130 BPM (460 ms je Schlag) kamen sie zu spät oder
  wurden übersprungen. Jetzt meldet das Gerät Schlagnummer und Tempo, die Oberfläche rechnet die halbe Laufzeit
  heraus und zählt selbst flüssig weiter (gemessen in einer Nachbildung mit 50–400 ms Laufzeit: höchstens 9 ms
  daneben). Die Phrasenanzeige unter Feinabstimmung nutzt dieselbe Uhr.

## 0.9.16

- **Eine Quelle für Lied und Position: AirPlay.** Titel, Interpret, Liedwechsel, Position im Lied, Spulen und
  Pause kommen jetzt von den AirPlay-Metadaten, also aus demselben Strom wie der Ton. Die Spotify-Integration in
  HA lag bis 11 s daneben und wird für die Show nicht mehr gebraucht. Der Titel wird jede Sekunde geprüft (bisher
  alle 2 s). Ist die Audioanalyse aus, startet die Party-Automatik, wenn AirPlay ein laufendes Lied meldet.
- **Lichtthema am Liedtitel:** Das Thema (und ein neu gewürfeltes) hängt an Interpret und Titel statt an der
  Spotify-ID. Bisher gewürfelte Themen gelten deshalb nicht mehr.
- **Spotify-Player nur noch optional:** Die Add-on-Option wird nur noch für die Warnung „Spotify spielt, aber kein
  Ton kommt an“ gebraucht. Fällt der Empfänger aus der Gruppe in Music Assistant, kommen auch keine AirPlay-Daten
  mehr an; dann weiß nur HA, dass Spotify spielt. Die Kachel „Spotify“ heißt jetzt „Lied“.
- **Ursache der stehenden Köpfe gefunden:** Lief ein Lied ohne Tempo bei FreqBlog, schätzte die Analyse das Tempo
  selbst, in float32 (numpy). Darüber wurde auch der Zeitpunkt des Schlags (Uhrzeit, 1,8 Mrd. s) zu float32 und
  war nur noch auf 128 s genau: Die Phase war danach immer 0, die Schlagzählung stand bei jedem eingerasteten Takt
  still, bei allen folgenden Liedern bis zum Neustart des Add-ons. Daraus folgten die „HA neu ausgerichtet“ alle
  10 s, das Abschalten der Audio-Zählung und das scheinbar schwer erkannte Lied. Periode und Schlag-Zeitpunkt
  bleiben jetzt immer normale Zahlen (float64). Die Diagnose aus 0.9.15 ist wieder entfernt.

## 0.9.15

- **Diagnose:** Die Schlagzählung stand auf dem Gerät bei eingerastetem Takt still (Schlagnummer exakt ganzzahlig,
  die Phase aus der Analyse kam offenbar als 0 an); mit dem aufgenommenen Ton läuft dieselbe Kette auf dem Mac
  richtig. Status und Aufnahme zeigen jetzt Phase, Raster-Zeitpunkt und Periode, wie sie im Show-Motor ankommen.

## 0.9.14

- **Position im Lied von AirPlay:** shairport-sync gibt jetzt die Metadaten von Music Assistant weiter (Titel,
  Interpret, Fortschritt, jede Sekunde eine Zeitmarke Abtastwert → Uhrzeit); die Lichtregie liest sie mit
  (`airplay.py`). Passt der AirPlay-Titel zur Show, kommt die Position im Lied von dort, genau und im Takt des
  Tons, sonst wie bisher von HA. Die Spotify-Position aus HA lag bis 11 s daneben (sie zeigt, wie weit Spotify
  ist, nicht was gerade erklingt). Was ankommt, steht im Log und unter Einrichten → Technik.
- **Show stand bei pumpendem Bass still:** Bei „ich jogge“ (Haller) meldete die Analyse alle paar Sekunden einen
  Drop. Jeder zog die Schlagzählung an den Phrasenanfang zurück (bis 12 Schläge), die Zählung blieb bei Schlag
  94–96 stehen und die Köpfe mit ihr. Ein Drop verschiebt die Zählung jetzt höchstens einmal in 64 Schlägen.

## 0.9.13

- **HA-Position lag daneben, nicht der Ton:** Bei „My Life Got Better“ lag die Spotify-Position aus HA (über Music
  Assistant) um 23 Schläge (ca. 11 s) daneben. Die Lichtregie zog ihre Zählung zweimal zu HA und schaltete die
  Zählung aus dem Ton dann für das Lied ab; danach rückte Beat This die „1“ alle 20 s um einen halben Takt zurecht.
  Jetzt gilt: Hat Beat This Schläge und „1“ bestätigt, wird bei großer Abweichung HA neu ausgerichtet und die
  Zählung bleibt. Ist die Zählung aus dem Ton schon abgeschaltet, schaltet eine Bestätigung von Beat This sie
  wieder an.

## 0.9.12

Oberfläche aufgeräumt:
- **Feinabstimmung** enthält nur noch, was man während der Party anfasst: Takt-Sync („Jetzt ist die 1“, ±1 Schlag,
  „1“ mit Beat This; ±1 Takt und die „1“ der Phrase aufklappbar) und den Rhythmus der Lampen.
- **Einrichten** sammelt, was man einmal einstellt: Ton und Takt (Audio, Takt-Test, Ton-Vorlauf), Lampen-Test und
  Vorlauf, Bewegung der Köpfe, Laser-Bereich. Dazu die zugeklappte Karte **Technik und Fehlersuche** mit Bildrate,
  Sender (Lücken, verworfene Pakete), Beat This, Lampenbefehlen und der Aufnahme.
- Doppelte Schalter entfernt: „Senden“ beim Laser von Hand (gleich dem Laser-Schalter auf der Show-Seite) und die
  eigene Karte „Automatik“ (die Zeit bis zum Aus steht jetzt beim Automatik-Schalter).

## 0.9.11

Aufgeräumt, ohne Änderung an der Show:
- **„1“ aus dem Klangwechsel entfernt:** lief seit 0.9.8 nur noch ohne Beat This und traf in den Aufnahmen kaum.
  Ohne Beat This ist die „1“ jetzt geschätzt (Drop und Phrasenwechsel ziehen die Zählung weiter nach).
- **Regler „Audio-Versatz“ entfernt:** Den Abgleich macht seit 0.8.15 der Ton-Vorlauf; der Versatz stand auf 0.
- Unbenutzte Werte in der Audioanalyse (Onset-Liste, Pegelspitze der Rohdaten) und in Beat This entfernt, alte
  Umstellungen der Einstellungen gestrichen.
- Gemeinsame Funktion für die JSON-Dateien (`jsonfile.py`) statt eigener Lese- und Schreibroutinen in fünf
  Modulen; die Abfrage „Audio vorhanden und an“ steht nur noch an einer Stelle.

## 0.9.10

- **Ohne Party kein Art-Net:** Bisher gingen 40-mal pro Sekunde Pakete an Köpfe und Laser, auch wenn deren
  Steckdosen aus waren. Gesendet wird jetzt nur während der Party, gut 5 s danach (Köpfe dunkel in die
  Parkposition) und 5 Minuten lang nach einer Bedienung von Hand (Köpfe einrichten, Laser von Hand).

## 0.9.9

- **Sender wartet nie mehr auf abgeschaltete Knoten:** War ein Art-Net-Knoten aus (Steckdose der Köpfe nach der
  Party, Laser-Steckdose aus, Knoten fährt gerade hoch), hielt der Pi die Pakete zurück, bis er den Knoten im
  Netz gefunden hätte; war der Puffer voll, blockierte das Senden bis zu 1,7 s. Gemessen nach der Party: 20 statt
  40 Bilder/s. Während der Party hätte ein ausgeschalteter Laser so auch die Köpfe ruckeln lassen. Jetzt wird ein
  Paket, das nicht sofort raus kann, verworfen (das nächste kommt 25 ms später); die Anzahl steht im Status.

## 0.9.8

- **Szene „vorher“ übernimmt keine Party-Farben mehr:** Beim Party-Start wurde der Zustand immer neu gesichert,
  auch wenn das Zurücksetzen nach der letzten Party gescheitert war; die Party-Farbe (Schrank 1 lila) wurde so
  zum neuen „vorher“. Jetzt merkt sich die Lichtregie die zuletzt gesendete Show-Farbe je Lampe. Leuchtet eine
  Lampe beim nächsten Start noch darin, bleibt die alte Szene.
- **Zurücksetzen wird geprüft:** Nach der Party prüft die Lichtregie nach 5, 20 und 65 s, ob alle Lampen wieder wie
  vorher sind, und wendet die Szene nur dann noch einmal an. Nach 2 Minuten steht im Log, ob es geklappt hat.
- **Abgelehnte Lampenbefehle werden wiederholt:** Bisher galt ein abgelehnter Befehl als gesendet, die Lampe blieb
  bis zum nächsten Wechsel (mindestens 2 Takte) falsch. Jetzt kommt nach 1 s ein neuer Versuch (im Budget).
- **Lampengruppen senden gleichzeitig:** Ambilights und Schränke warten nicht mehr aufeinander; ein langsamer
  Befehl schiebt die anderen Lampen nicht mehr hinter den Schlag.
- **Kein Hänger mehr alle 20 s:** Für Beat This wurden 35 s Ton unter der Sperre der Audioanalyse
  zusammengesetzt; so lange wartete die Show-Schleife auf Phase und Pegel. Gesperrt wird jetzt nur noch kurz.
- **Weniger Last durch die Oberfläche:** Sie fragt 5-mal pro Sekunde den Status. Die teuren Messwerte
  (Sender, Lampen, Aufnahmen, Beat This, Eingangsrate) werden nur noch einmal pro Sekunde gerechnet.
- **„1“ am Liedanfang ruhiger:** Die alte Erkennung aus dem Klangwechsel läuft mit Beat This nicht mehr mit. Sie
  traf in den Aufnahmen kaum und verschob am Liedanfang die Zählung, bis Beat This sie zurückschob. Spart
  außerdem Rechenzeit bei jedem Audio-Schritt. Ohne Beat This arbeitet sie wie bisher.
- **Beat This erholt sich:** Antwortet der Rechenprozess 60 s nicht, wird er beendet und neu gestartet; bisher
  gab es danach bis zum Neustart des Add-ons keine „1“ mehr.

## 0.9.7

- **Lampen nach der Party zurück:** Nach einem Stopp blieb Schrank 1 in den Farben der Party (lila), die anderen
  Lampen kamen erst nach gut einer Minute zurück. Direkt nach der Show ist die Befehlsgrenze der Yeelights oft
  noch erschöpft, einzelne Lampen lehnen die Szene „vorher“ dann ab. Die Szene wird jetzt nach 5, 20 und 65 s
  noch einmal angewendet (bisher einmal nach 5 s).
- **Laser aus heißt aus:** Beim Abschalten des Lasers in der Oberfläche hörte der Sender nur auf zu senden; der
  Art-Net-Knoten hielt das letzte Bild, und der Laser zeigte die letzte Figur ohne Animation weiter. Jetzt geht
  noch 1 s lang „Laser aus“ raus, erst dann hört der Sender auf.

## 0.9.6

- **Lampenfarben passen zur Show:** Ambilights und Schränke zeigen nur noch die beiden Farben der Köpfe (Grund-
  und Akzentfarbe des Liedes), im Wechsel: Zeigen die Ambilights die eine, zeigen die Schränke die andere.
  Höhepunkt und Drop: alles in der Akzentfarbe. Bisher kam eine dritte Farbe dazu, die die Köpfe nie zeigen.
- **Grenze der Yeelights:** HA meldete wieder „client quota exceeded“ (Schrank-Streifen). HA schickt vor Farbe
  oder Helligkeit ein Einschalten mit, das zählt jetzt im Budget. Die Schränke wechseln alle 2 Takte statt
  jeden Takt, die Ambilights höchstens alle 2 Takte (Standard 2 Takte, auch 4 und 8 Takte oder nach Lied).
- **Drop und Break rechtzeitig bei den Lampen:** Die Analyse hat den Ton 1 s vor dem Lautsprecher. Die Lampen
  nehmen den Zustand (Drop, Break, Pegel) um ihren Vorlauf voraus und reagieren so trotz Verzögerung auf dem
  Schlag.

## 0.9.5

- **Gemessenes Tempo greift auch ohne eingerasteten Takt:** Bei „Drifting (SISTEK Remix)“ meldete FreqBlog
  122,1 BPM, Beat This maß 145,8 BPM, die Zählung lag nach kurzer Zeit 21 Schläge zurück. Die Show stellte aber
  nicht um: Ergebnisse von Beat This wurden nur bei eingerastetem Audio-Takt verarbeitet, und der kann bei
  falschem Tempo aus der Datenbank gar nicht einrasten (die Analyse ist auf dieses Tempo festgelegt). Jetzt rechnet
  Beat This, sobald Ton ankommt, und das Tempo wird ohne eingerasteten Takt übernommen; nur die „1“ braucht ihn.

## 0.9.4

- **Gleichmäßigere Bewegung:** Show und Art-Net-Sender liefen mit zwei eigenen, leicht verschiedenen Takten
  (ca. 39 und 38 pro Sekunde) nebeneinander; dabei ging regelmäßig ein Bild doppelt raus oder fiel aus. Jetzt
  schickt der Sender jedes Show-Bild sofort, wenn es fertig ist (ohne Show weiter 40-mal pro Sekunde). Die
  Show-Schleife hält ihren Takt fest gegen die Uhr (Bild k zur Zeit Start + k/40 s), statt nach jedem Bild fest
  25 ms zu warten; eine Verzögerung verschiebt so nicht alle folgenden Bilder. Am Mac: 39,9 Bilder/s, größte
  Lücke 35 ms, kein Ruckler.
- Messung: Takt-Sync-Anzeige und Status zeigen für die Sendungen die größte Lücke und die Ruckler (> 50 ms) der
  letzten 10 s.
- **Die fertige Show messen:** Die Aufnahme speichert jetzt je Bild (40 pro Sekunde), was an die Köpfe geht (Pan,
  Tilt, Helligkeit), dazu jede Art-Net-Sendung. Neuer Knopf „Hängt jetzt“ markiert Stellen, an denen die Köpfe
  stocken. Auswertung mit `dev/show_auswerten.py`: Lücken, Stillstand je Kopf mit Szene, und für jede Markierung
  die 3 s davor (Lücken, Stillstand, Szene, Ereignisse der Schlagzählung).
- Enthält 0.9.3 (nicht eingespielt).

## 0.9.3 (nicht eingespielt, in 0.9.4 enthalten)

- **Gemessenes Tempo schlägt die Datenbank:** Die Datenbank gilt nur, bis Beat This das Lied gemessen hat.
  FreqBlog meldete z. B. für „Another World“ (MEDUZA) 65 BPM, Beat This maß 130,04 BPM. Bis 4 % Abweichung wird
  das Tempo fließend übernommen; bei größerer Abweichung (z. B. doppelt oder halb) startet die Show das Lied mit
  dem gemessenen Tempo neu, sobald zwei Messungen hintereinander übereinstimmen (Zählung, HA-Abgleich und Bahnen
  hängen am Tempo). Bisher galt das Modell nur bis 4 % Abweichung.
- Das gemessene Tempo wird je Lied gespeichert (`tempo_korrektur.json`) und gilt beim nächsten Abspielen sofort,
  auch die kleinen Korrekturen bis 4 %.

## 0.9.2

- **Beat This mit weniger Last:** Am Pi gemessen: 16 s Ton in 7,2 s (Spektrogramm 0,3 s, Vorbau 4,0 s,
  Transformer 2,8 s; numpy 2.4.6 mit OpenBLAS 0.3.30). Mit den Aufnahmen verglichen (Fenster/Abstand → „1“
  getroffen): 30 s/15 s 93 %, 16 s/20 s 95 %, 16 s/30 s 88 %, 12 s/20 s 63 %. Jetzt 16 s Ton alle 20 s: Der
  Rechenprozess arbeitet gut ein Drittel der Zeit statt fast ununterbrochen.

## 0.9.1

- **Messung der Rechenzeit von Beat This am Pi:** Am Pi 5 brauchte das Modell 33 s für 30 s Ton (am Mac 1,5 s)
  und rechnete damit praktisch ununterbrochen (ca. 53 % CPU des Add-ons). Seltener rechnen hilft nicht (in den
  Aufnahmen sank die Trefferquote mit einer Rechnung pro Minute von 93 % auf 62 %). Deshalb zuerst messen: Der
  Rechenprozess schreibt je Lauf die Zeit für Spektrogramm, Vorbau und Transformer sowie die BLAS-Bibliothek von
  numpy ins Add-on-Log.
- Aufmerksamkeit mit zusammenhängendem Speicher (nicht zusammenhängende Matrizen können numpy auf langsamere
  Rechenwege zwingen).
- Alle „1“-Schläge des Fensters zählen (vorher fielen ältere als 45 s heraus, bei 33 s Rechenzeit fast alle).

## 0.9.0

- **Die „1“ im Takt mit Beat This!** (neuronales Modell, Foscarin/Schlüter/Widmer, ISMIR 2024, MIT-Lizenz):
  Alle 15 s rechnet das Modell im Hintergrund über den Ton dieses Liedes (bis 30 s) und liefert Schläge und
  „1“-Schläge. Liegt die große Mehrheit auf derselben Position im Takt, wird sie zur „1“ („Takt-Anker (Beat
  This)“); gezählt wird dabei in Schlägen des Modells, damit ein leicht falsches Tempo aus der Datenbank nicht
  stört. Liegt das Tempo des Modells bis 4 % neben der Datenbank, übernimmt die Show das genaue Tempo.
  Gemessen mit 6 Aufnahmen vom Gerät (ganze Kette nachgespielt, mit Ton-Vorlauf): 93 % der Markierungen „Hier
  ist die 1“ liegen auf der gezählten „1“ (vorher am Gerät 14 %).
- Das Modell läuft in numpy nachgebaut (im Add-on gibt es kein PyTorch): Gewichte als float16 in
  `app/modelle/beat_this.npz` (38 MB), geprüft gegen das Original (gleiche Schläge und „1“, Logits höchstens 0,04
  daneben). Es rechnet in einem eigenen Prozess mit niedriger Priorität und 2 Rechenkernen, damit die Show nicht
  ruckelt. Schalter „„1“ mit Beat This“ unter Feinabstimmung; Rechenzeit in der Audio-Zeile.
- Ton-Vorlauf (siehe unten, aus der nicht eingespielten 0.8.15).

## 0.8.15 (nicht eingespielt, in 0.9.0 enthalten)

- **Ton-Vorlauf:** Der Empfänger (shairport-sync über stdout) bekommt den Ton etwa 1,0 s bevor der Lautsprecher
  ihn spielt (Puffer 1 s). Gemessen mit 6 Aufnahmen und dem Modell Beat This!: Mit 1,03 s Verschiebung lagen
  die Markierungen „Hier ist die 1“ zu 93 % auf der „1“ des Modells (inklusive ca. 30 ms Tipp-Verzögerung).
  Bisher glich die Show nur 80 ms aus: Schlag und „1“ lagen je nach Tempo daneben (der Takt-Test passte nur bei
  einem Tempo), Break und Drop kamen eine Sekunde zu früh. Jetzt läuft alles aus dem Ton um den Ton-Vorlauf
  zurückversetzt (Einstellung unter Feinabstimmung, Standard 1,0 s); Pegel, Break und Drop werden dafür 4 s
  lang zwischengespeichert.
- Audio-Versatz neu um 0 ms (gemessen: das Schlagraster liegt im Mittel 6 ms neben den Schlägen des Modells);
  ein gespeicherter alter Wert wird einmalig auf 0 gesetzt.

## 0.8.14

- **Aufnahme für die Fehlersuche** (Feinabstimmung): schneidet 90 s Ton am Empfänger mit und dazu, was die
  Erkennung in jedem Bild entschieden hat (Schlagnummer, HA-Schätzung, Break, Drop, Korrekturen). Mit „Hier ist
  die 1“ lässt sich während der Aufnahme die echte „1“ markieren, ohne die Show zu ändern. Die Aufnahme lässt
  sich als ZIP herunterladen; die letzten 12 bleiben auf dem Gerät.
- Werkzeug `dev/nachspielen.py`: spielt eine Aufnahme auf dem Mac durch Analyse und Schlagzählung, mit denselben
  Blöcken und Zeitstempeln wie am Gerät, und vergleicht die gezählte „1“ mit den Markierungen.

## 0.8.13

- **Die „1“ im Takt aus dem Audio:** Tempo und Schlag kamen schon aus dem Audio, welcher Schlag die „1“ ist
  aber aus der Spotify-Position (auf 1–3 s genau, also 2–6 Schläge): Der Einsatz im Takt war Glückssache.
  Jetzt misst die Analyse je Schlag, wie stark sich der Klang gegenüber dem vorigen ändert (Akkord, Bass-Ton,
  neue Instrumente kommen meist auf der „1“), und summiert das über mehrere Takte auf die vier Positionen im
  Takt. Ist eine Position deutlich die stärkste (mindestens 1,25-mal), wird sie zur „1“ („Takt-Anker“).
  Danach verschieben Drop, Phrasenwechsel und HA-Abgleich nur noch um ganze Takte. „Jetzt ist die 1“ oder
  ±1 Schlag von Hand hat Vorrang und gilt für das ganze Lied.
- Takt-Sync-Anzeige: woher die „1“ kommt (aus dem Audio mit Deutlichkeit, von Hand, oder noch geschätzt).
- **Lampen an der Grenze der Yeelights:** Am Gerät meldete HA bei schnellen Wechseln „client quota exceeded“:
  Die Yeelights nehmen nur etwa 60 Befehle pro Minute je Lampe an, und HA schickt Farbe und Helligkeit als zwei
  Befehle. Deshalb:
  - Farbwechsel der Ambilights höchstens einmal pro Takt (jeder Takt, 2 Takte, 4 Takte, nach Lied).
  - „Dunkel vor dem Wechsel“ entfernt (kostete einen weiteren Befehl je Wechsel und sah nicht gut aus).
  - Gesendet wird nur, was sich ändert: Ein Farbwechsel ist nur die Farbe, das Wechselspiel der Schränke nur
    die Helligkeit.
  - Budget je Lampengruppe (50 Befehle pro Minute): Ist es aufgebraucht, wird ein Wechsel ausgelassen, statt
    dass die Lampe ihn ablehnt.

## 0.8.12

- **Ambilights: harte Farbwechsel auf dem Schlag.** Der Rhythmus ist einstellbar (¼ Schlag bis 4 Takte oder wie
  bisher nach dem Lied), dazu „Harter Wechsel“ (ohne Übergang) und „Dunkel vor dem Wechsel“: Die Ambilights
  gehen kurz vorher aus und kommen auf dem Schlag in der neuen Farbe wieder (0–75 % eines Schlags). Dunkel
  wird nur, wenn sich die Farbe wirklich ändert.
- Lampen-Schleife rechnet alle 20 ms statt alle 250 ms und sendet nur Gruppen, die sich ändern (Ambilights
  zuerst). Der Vorlauf lässt sich in 0,05-s-Schritten einstellen.
- **Lampen-Test** unter Feinabstimmung: Die Ambilights wechseln im eingestellten Rhythmus zwischen rot und
  blau. Damit den Vorlauf einstellen und ausprobieren, wie schnell die Lampen mitkommen.
- Messwerte in der Lampen-Karte: Befehle pro Minute, Dauer eines Befehls an HA, Fehler.
- **Show nur mit Ton:** Ging die Musik aus, lief die Show bisher weiter, weil HA eine Pause erst nach bis zu 30 s
  meldet; die Ruhe-Animationen kamen kaum zum Zug. Jetzt gilt der Ton am Empfänger: nach 2 s ohne Ton die
  Pause-Animation, nach 10 s geht die Show aus und die Warte-Animation (Sternhimmel) übernimmt. Kommt wieder
  Ton, startet die Show sofort, auch wenn HA noch „pausiert“ meldet. Ohne Audio (Schalter aus) wie bisher nach HA.
- Warnung „kein Audio, obwohl Spotify spielt“ erst nach 45 s statt 15 s, damit eine normale Pause sie nicht auslöst.

## 0.8.11

- **Show blieb stehen, obwohl Musik lief:** Am Gerät lief die Schlagzählung deutlich langsamer als die Musik
  (nach 40 s 23 Schläge zurück). Nach zwei Korrekturen schaltete 0.8.9 den HA-Abgleich ab, danach stand die
  Show praktisch still, während die Analyse „sicher 100 %“ meldete (sie prüft nur, ob die Kicks zu ihrem eigenen
  Raster passen). Jetzt wird in diesem Fall die Audio-Zählung für das Lied abgeschaltet und nach der HA-Position
  weitergezählt: Die Show läuft im Tempo weiter, die Takt-Effekte gelten dann nicht als eingerastet.
- **Break blieb hängen:** Die Bass-Spitze, an der Breaks gemessen werden, klang nur sehr langsam ab. Nach einer
  lauten Stelle galt danach jedes Stück als „Break“ (ruhige Szenen, Spots treffen sich, kein Drop). Jetzt werden
  die Pegel bei jedem neuen Lied neu angesetzt, und ein „Break“ über 30 s gilt als falsche Spitze.
- **Leser:** Endete ein Lesevorgang mitten in einem Stereo-Frame, wurde der Rest verworfen; danach war der Ton
  dauerhaft verschoben und wurde als Rauschen gelesen. Der Rest wird jetzt aufgehoben.
- Diagnose: Status zeigt die Eingangsrate des Tons (`eingang`, 1,0 = Echtzeit) sowie Schlagnummer, Abweichung zu
  HA und ob die Audio-Zählung aus ist (unter `sync`).

## 0.8.10

- **Ruhe-Animationen**, wenn keine Musik läuft:
  - *Warten* (Party an, noch keine Musik, oder ein Lied ohne Tempo): Sternhimmel an der Decke. Beide Köpfe
    ziehen langsam gegenläufig Kreise (40 s pro Runde), Gobo Punkte-Ring, sanftes Atmen; die Farbe wechselt
    alle 24 s, der Radwechsel passiert im Dunkeln. Laser aus.
  - *Pause* (Spotify pausiert): Beide Spots treffen sich über dem TV, pendeln leicht gegeneinander und atmen in
    der Grundfarbe des Liedes. Bisher blieben sie einfach stehen.
  - Beim Ausschalten wie bisher: dunkel in die Parkposition, dann Steckdosen aus.

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

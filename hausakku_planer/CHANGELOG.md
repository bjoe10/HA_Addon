# Changelog

## 0.12.1
- Hängende Läufe lassen sich finden: Eine Minute vor dem Zeitlimit schreibt der Lauf ins Protokoll, wo er wartet (Schritt, Stacks der Tasks und Threads). Die Ausgabe ist ungepuffert, auch ein abgebrochener Lauf behält sie.
- Bleibt eine Antwort von Home Assistant über den WebSocket 3 Minuten aus, ist das jetzt ein Fehler, der den Befehl nennt, statt eines Laufs, der bis zum Zeitlimit hängt.
- Fehlgeschlagene Läufe nennen im Protokoll die Code-Stelle, auch stille Nachplanungen.

## 0.12.0
- **Ersparnis neu gerechnet:** Ein Schatten-Akku mit dauernd eingeschaltetem Wechselrichter läuft in Viertelstunden durchgehend mit, aus den 5-Minuten-Werten von Home Assistant und den Tibber-Viertelstundenpreisen. Gezählt wird ab dem Update und **nur, solange die Steuerung an ist** (Freigabe-Schalter die ganze Viertelstunde an). Ist sie aus oder fehlen Daten, kommt nichts dazu; der Schatten übernimmt danach den gemessenen Akkustand.
- Aufgehobene Energie geht an Wochengrenzen nicht mehr verloren. Gesamt- und Wochenwert addieren sich exakt.
- Der Schatten nutzt den gemessenen Entlade-Wirkungsgrad und lernt, wie viel beim Versorgen trotzdem aus dem Netz kommt. Er rechnet sich also nicht besser als die echte Anlage.
- `sensor.<Präfix>_ersparnis`: Wert = Gesamtersparnis, Attribut `week_eur` = diese Woche, dazu letzte Woche, gezählte Stunden, Modellabweichung. Die Übersicht zeigt Gesamt und Woche.
- Die Wochenbilanz nennt den Zähler. Die bisherige Summe der Wochenbilanzen entfällt.

## 0.11.0
- **Gemessene Ersparnis** als Sensor `sensor.<Präfix>_ersparnis` (EUR): die Summe der Wochenbilanzen aller vollen Wochen gegenüber „Wechselrichter dauernd an, nie Netzladen“. In den Attributen stehen der Wert inklusive Akkustand, die letzte Woche und alle Wochen einzeln. Die Übersicht zeigt ihn als Kachel. Er wird mit jedem Lauf neu geschrieben, wie der Bericht-Sensor.
- Knopf **„Wochenbilanz rechnen“** auf der Übersicht. Damit lässt sich eine fehlgeschlagene Bilanz nachholen, etwa nach dem Austausch eines Zählers. Das Protokoll nennt solche Läufe „Wochenbilanz“.
- **Zeitlimit für Läufe** (Plan und Nachplanung 15 Minuten, Wochenbilanz 10 Minuten). Ein hängender Lauf wird beendet und als fehlgeschlagen protokolliert, mit der Ausgabe bis dahin. Vorher blockierte er alle folgenden Läufe, bis das Add-on neu gestartet wurde.

## 0.10.0
- **Dashboard-Karte** im Add-on: die Tibber-Prices-Preiskurve mit Akku-Linie (gemessen und geplant), Phasenplan, Kacheln für Akku, PV, Wechselrichter, Netz und Bezug heute, dazu wahlweise Uhr mit Preiszeiträumen, Vollbild für ein Display und Nachtmodus. „Karte einrichten“ in den Einstellungen legt sie als Dashboard-Ressource an (oder übernimmt eine frühere Kopie) und trägt die Helfer, den Akku und die Kapazität ein; danach hält das Add-on genau diese Ressource bei Updates und Einstellungsänderungen aktuell. Dashboards ändert es nicht.

## 0.9.3
- Der Bericht-Sensor (`sensor.<Präfix>_bericht`) trägt im Attribut `soc_plan` den geplanten Akkustand des zuletzt bestätigt veröffentlichten Plans (kWh am Ende jedes Intervalls), etwa für eine Akku-Linie im Dashboard. Ein nicht veröffentlichter Plan ändert es nicht.

## 0.9.2
- Bericht: Die PV-Prognose für heute ist nur der Rest ab Berichtszeit und wird so gekennzeichnet; zusätzlich steht die heute bisher gemessene PV drin. Vorher las sich abends „0,0 kWh“ wie ein Tageswert.

## 0.9.1
- „Steuerung einrichten“ bricht ab, wenn nicht geprüft werden kann, ob schon eine Steuerung existiert, und ist ausgegraut, wenn das Add-on keine Automationen anlegen darf.

## 0.9.0
- „Steuerung einrichten“ in den Einstellungen: legt den Blueprint und die Automation „Hausakku-Planer Steuerung“ in Home Assistant an (nach Bestätigung; nur mit eingeschaltetem Veröffentlichen und zugeordneten Schaltern; nie, wenn schon eine Steuerung diese Helfer benutzt). Die Freigabe bleibt aus, es wird nichts geschaltet.
- Der Blueprint liegt jetzt im Add-on selbst (`hausakku_planer/app/blueprint/steuerung.yaml`), eine Kopie für Add-on und Import.

## 0.8.0
- Die Add-on-Option „Betriebsstufe“ entfällt. Veröffentlichen wird nur noch in der Oberfläche (Einstellungen) geschaltet. Neue Installationen starten mit „aus“.

## 0.7.2
- Beim Start wird eine in der Add-on-Option gewählte Veröffentlichung einmalig als Einstellung übernommen. Die Einstellungsseite meldet, ob der Schalter gespeichert ist.

## 0.7.1
- „Schätzen“ ermittelt nur Kapazität und Ladeleistung; die Wechselrichter-Leistung ist nicht aus der Messung ableitbar (Ausgang folgt dem Hausverbrauch).
- „Vorschläge einsetzen“ sagt, wenn das Energie-Dashboard oder die Geräteliste nicht lesbar war.

## 0.7.0
- Einfachere Einrichtung: „Vorschläge einsetzen“ füllt leere Felder aus dem Energie-Dashboard, aus Sensoren am selben Gerät wie die Schalter und nach Namen vor (nichts wird überschrieben oder gespeichert).
- „Schätzen“ ermittelt Akku-Kapazität, Ladeleistung und Wechselrichter-Leistung aus den letzten 28 Tagen Statistik.
- Veröffentlichen ist ein Schalter in den Einstellungen statt einer Add-on-Option (kein Neustart nötig). Die alte Option gilt nur noch, solange der Schalter nie gespeichert wurde.
- Checkliste auf der Übersicht mit dem nächsten Schritt: Entitäten, erster Plan, Veröffentlichen, Steuerung (erkennt die Blueprint-Automation), Freigabe.

## 0.6.1
- Das Umschalten auf die Helfer eines anderen Planers ist nicht mehr in der Oberfläche einstellbar; ein bestehender Wert bleibt beim Speichern erhalten.

## 0.6.0
- **Blueprint „Hausakku-Planer Steuerung“** (`blueprints/automation/hausakku_planer/steuerung.yaml`): führt den Plan sicher aus, ohne eigenen Wächter-Sensor. Freigabe, Ablaufdatum und Datumsbindung, bestätigtes Aus mit Totzeit, Schaltsperre, Reserve mit Hysterese, Ladeziel, optionaler Batterie-Schutz (Spannung, Temperaturen, BMS-Herzschlag, Lade- und Entlade-Freigabe, externe Sperre). Mit 56 Simulationstests und gegen die echte Home-Assistant-Template-Engine geprüft.
- Das Add-on legt ab „Plan veröffentlichen“ auch die Freigabe (immer aus), den Übernahme-Marker und die Schaltsperre an; die Einstellungsseite zeigt, welche Werte im Blueprint zu wählen sind, samt Import-Link.
- Nennspannung des Akkus einstellbar (nur für die Wirkungsgrad-Messung); ohne Angabe keine Spannungsumrechnung.
- Die Betriebsstufe `control` entfällt: Das Add-on schaltet nie selbst, das übernimmt der Blueprint.
- Icon und Logo; ausführliche Dokumentation (Einrichtung, Sicherungen, Fehlersuche), README im Repository.

## 0.5.6
- Wochenbilanz-Fehlertext nennt Umfang des Preisarchivs und Kalibrierung.

## 0.5.5
- Wochenbilanz nennt bei zu wenigen vollständigen Stunden die Gründe (Zählung fehlender Preise und Messwerte).

## 0.5.4
- Wochenbilanz rechnet mit dem letzten lückenlosen Block aus Stunden mit Preis und vollständigen Messwerten (mindestens 24 Stunden), statt abzubrechen, wenn das Preisarchiv noch nicht die ganze Woche abdeckt. Der Zeitraum steht im Bericht.

## 0.5.3
- Wochenbilanz meldet bei einem Fehler die Fundstelle (Datei:Zeile).

## 0.5.2
- Fix: Zeitplan-Update schickt den vorhandenen Namen mit (Home Assistant verlangt ihn); 0.5.1 brach damit die Veröffentlichung ab.

## 0.5.1
- Bericht-Sensor enthält den vollständigen Bericht (vorher fehlte der Anfang).
- Beim Aktualisieren eines Zeitplan-Helfers bleibt sein Anzeigename erhalten; neue Helfer bekommen einen lesbaren Namen.
- Eine vorhandene Steuerung wird am Freigabe-Schalter erkannt; der Bericht behauptet nicht mehr „Schaltautomation nicht installiert“.

## 0.5.0
- Bericht-Sensor `sensor.<Präfix>_bericht`: nach jedem Lauf (Hauptlauf, Nachplanung, Wochenbilanz) liegt der Bericht samt Faktenblock als Attribut in Home Assistant, damit ein Assistent ihn lesen und zusammenfassen kann, ohne die Add-on-Schnittstelle zu brauchen.
- Wochenbilanz läuft montags 08:00 im Add-on.
- „Helfer übernehmen“: für den Umstieg von einem bestehenden Planer mit den Namen `hausakku_*` (Präfix `hausakku` ist nur damit erlaubt).

## 0.4.0
- Eigene Helfer mit einstellbarem Präfix (Standard `hap`, also `schedule.hap_netzladen`, `input_number.hap_ziel_soc` usw.). Die Stufe „Plan veröffentlichen“ schreibt nur dorthin.
- Präfixe, die mit `hausakku` beginnen, sind gesperrt, damit Helfer eines anderen Planers mit diesen Namen nie überschrieben werden.
- Der Freigabe-Schalter wird ebenfalls aus dem Präfix abgeleitet.

## 0.3.0
- Preisquelle wählbar: Tibber, ein Sensor in Home Assistant mit Preisliste (Nordpool, EPEX Spot und ähnliche) oder Börsenpreis (energy-charts) mit Aufschlag und MwSt.
- Stundenpreise werden auf Viertelstunden erweitert, Einheiten (EUR/kWh, ct/kWh, EUR/MWh) werden erkannt.
- „Preise prüfen“ in den Einstellungen zeigt, was der Planer sieht (Zeitraum, Preisspanne, aktueller Preis, Lücken).
- Mehrere Tibber-Zuhause: Auswahl in den Einstellungen statt Abbruch.
- Börsenpreis-Cache pro Gebotszone.

## 0.2.3
- „Jetzt rechnen“ startet den Lauf im Hintergrund; die Oberfläche zeigt den Fortschritt, kein Zeitlimit mehr bei langen Läufen.
- Berichtstexte ohne Annahmen eines einzelnen Haushalts (kein „Tesla“, keine festen Akku- und WR-Angaben).
- Fahrzeug-Ladefenster: Der Bericht behauptet nur dann einen Eintrag in HA, wenn wirklich einer geschrieben wurde; ohne eingerichteten Helfer wird nichts versucht.

## 0.2.2
- Einstellungen: Lade- und WR-Leistung sowie Preisuntergrenze.
- Entitätsvorschläge besser sortiert (wichtige Stichworte zuerst, nicht verfügbare ans Ende).

## 0.2.1
- Docker-Build repariert: Basis-Image über build.yaml (das bisher genutzte Image existiert nicht).
- Standardwerte-Datei umbenannt, damit Supervisor sie nicht als Add-on-Konfiguration liest.

## 0.2.0
- Native Home-Assistant-Anbindung (REST/WebSocket), kein MCP mehr.
- Entitäten über Einstellungen zugeordnet statt fest verdrahtet.
- Scheduler und Laufprotokoll.
- Weboberfläche (Ingress): Übersicht, Plan mit Diagrammen, Protokoll, Einstellungen mit Prüfung der Entitäten.

## 0.1.0
- Gerüst, noch ohne Funktion.

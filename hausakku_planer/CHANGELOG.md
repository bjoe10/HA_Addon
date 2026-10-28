# Changelog

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

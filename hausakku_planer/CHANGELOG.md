# Changelog

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

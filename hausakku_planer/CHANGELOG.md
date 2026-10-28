# Changelog

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

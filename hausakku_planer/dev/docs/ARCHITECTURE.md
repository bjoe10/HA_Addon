# Hausakku-Planer als Home-Assistant-Add-on: Architektur

Ziel: Ein Add-on, das für **beliebige** Haushalte mit Heimspeicher und dynamischem Stromtarif nutzbar ist,
ohne Agenten-Framework, MCP oder feste Geräte-Namen. Es geht aus einem privaten Einzelprojekt hervor, dessen Planer-Kern übernommen wurde.

## Grundsätze

1. **Nur Home-Assistant-APIs.** Zugang über den Supervisor-Proxy (`SUPERVISOR_TOKEN`, REST + WebSocket). Keine Fremddienste außer optional Open-Meteo/Energy-Charts.
2. **Nichts Persönliches im Code.** Alle Entitäten, Standort, Grenzwerte und Hardware-Daten kommen aus der Konfiguration. Defaults sind neutral.
3. **Sicher starten.** Ein frisches Add-on steht auf `Beobachten`: es rechnet und zeigt Pläne, schreibt aber nichts. Schreiben und Steuern sind getrennte, bewusste Stufen.
4. **Der Plan überlebt das Add-on.** Wie im Original läuft die Hardware-Steuerung nicht im Add-on, sondern als generierte HA-Automation mit Ablaufdatum und Schutzbedingungen. Fällt das Add-on aus, läuft der letzte gültige Plan bis zum Ablauf, danach sicherer Fallback.
5. **Kern bleibt unverändert.** Optimizer, Prognosen, Mehrtagessicht und deren Tests (263) sind die wertvolle Substanz und werden nur an die neue Umgebung angeschlossen.

## Betriebsstufen

| Stufe | Add-on tut | Schreibt in HA |
|---|---|---|
| `observe` (Standard) | liest, rechnet, zeigt Plan in der Oberfläche | nichts |
| `publish` | zusätzlich Plan in eigene Helfer/Zeitpläne | nur eigene Objekte mit Präfix |
| `control` | zusätzlich Steuer-Automation installieren und freigeben | Automation + Freigabe-Schalter, Nutzer bestätigt in der Oberfläche |

## Komponenten

```
┌──────────────────────── Add-on-Container ────────────────────────┐
│  Web-UI (Ingress)  ◄────── REST ──────►  Dienst (asyncio)         │
│   Status · Plan · Kurven                  ├─ Scheduler            │
│   Einrichtung · Protokoll                 ├─ Collector (HA-API)   │
│                                           ├─ Planner/Optimizer    │
│                                           ├─ Publisher            │
│                                           └─ Notifier (notify.*)  │
│  /data: Optionen, State, SQLite-Audits, Lernmodelle               │
└───────────────┬───────────────────────────────────────────────────┘
                │ http://supervisor/core/api  ·  ws://supervisor/core/websocket
                ▼
          Home Assistant (Recorder, Services, Helfer, Automationen)
```

### HA-Schicht (`ha/`)
Ersetzt `ha_client.py` (MCP). Schmale, getestete Schnittstelle:

| Bisher (MCP-Tool) | Neu |
|---|---|
| `ha_get_state` | `GET /api/states/<id>` |
| `ha_get_history` (Statistik) | WS `recorder/statistics_during_period` |
| `ha_get_history` (States) | `GET /api/history/period` |
| `ha_call_service` mit Antwort | `POST /api/services/<d>/<s>?return_response` |
| `ha_eval_template` | `POST /api/template` |
| `ha_config_set_helper` (schedule, input_*) | WS `schedule/*`, `input_*/*` |
| `ha_manage_energy_prefs` | WS `energy/get_prefs` |
| Automation lesen/schreiben | REST `/api/config/automation/config/<id>` |

Die Schreib-Allowlist des Originals bleibt als Schutzprinzip: eine Liste erlaubter Domänen/Objekte, alles andere wirft.
Zwischenschritt: eine Kompatibilitätsschicht liefert zunächst die bisherigen Datenformen an `collector`/`publisher`, damit der Kern ohne Neuschreiben getestet bleibt; sie wird schrittweise durch typisierte Rückgaben ersetzt.

### Konfiguration statt Konstanten
Die festen Namen aus `collector.py`/`controller_config.py` werden zu Optionen:

- **Netz:** Bezugszähler, Einspeisezähler (kWh, total_increasing)
- **Speicher:** SOC, Spannung, Kapazität (kWh), Lade-/Entladeleistung, optional BMS-Schutzsensoren
- **Schaltung:** Ladegerät-Schalter, Wechselrichter-Schalter (oder eine generische Aktion für beides)
- **PV:** Erzeugungszähler, Standort (Breitengrad/Längengrad, Neigung/Ausrichtung optional)
- **Preise:** Anbieter (siehe unten)
- **Fahrzeug (optional):** Ladezähler zum Herausrechnen, SoC, Ziel-SoC
- **Tarif:** Fixe Aufschläge, Preisuntergrenze, Verlust-/Wirkungsgrad-Startwerte (werden gemessen und überschrieben)

Ein **Einrichtungsassistent** in der Oberfläche schlägt Entitäten vor (Geräteklasse `energy`, Einheit kWh, Name enthält z. B. „soc“) und prüft sie sofort: liefert der Zähler Statistik, ist die Einheit passend, gibt es 28 Tage Verlauf.

### Preisanbieter (`prices/`)
Austauschbar hinter einer Schnittstelle `get_prices(start, end) -> [(start, eur_per_kwh)]`:
`tibber` (HA-Dienst `tibber.get_prices`), `ha_entity` (Sensor mit Attributliste, z. B. Tibber/Nordpool/EPEX/aWATTar-Integrationen), `awattar`, `energy_charts` (Börsenpreis plus konfigurierbarer Aufschlag). Die Tail-Prognose (Mehrtagessicht) und Energy-Charts-Historie bleiben optional.

### Steuerung
Die Guard-Vorlage des Originals ist auf eine Hardware (ANT-BMS, Zigbee-Schalter) zugeschnitten. Neu: der Guard wird **aus der Konfiguration generiert**; Schutzbedingungen sind optional und werden nur eingebaut, wenn der Sensor zugeordnet ist. Pflicht bleibt: Ablaufdatum, Datumsbindung der Fenster, Lader/WR nie gleichzeitig, Totzeit, Handüberschreibung respektieren, Freigabe-Schalter. Installation nur in Stufe `control` und nur nach Bestätigung mit Vorschau des YAML.

### Scheduler
Eigene Schleife im Dienst statt eines externen Cron-Dienstes: täglicher Hauptlauf, stündliche stille Nachplanung, Wochenbilanz; Zeiten in den Optionen. `flock`-Sperre bleibt. Manueller „Jetzt rechnen“-Knopf in der Oberfläche.

### Benachrichtigung
Regelbasierter Text aus dem vorhandenen Faktenblock über beliebige `notify.*`-Dienste. Die Qwen-Zusammenfassung entfällt oder wird optional über eine OpenAI-kompatible URL angebunden.

### Daten (`/data`)
Statt `state/` im Repo: Optionen aus `/data/options.json`, Laufzeit-State, SQLite-Audits und Lernmodelle in `/data`. Ein zentrales `paths.py` ersetzt alle `BASE/...`-Zugriffe. Rolling-Archive werden begrenzt (Snapshots, Audits), damit der Speicher nicht wie im Original auf >150 MB wächst. Backups des Add-ons enthalten `/data`.

## Weboberfläche (Ingress)

Leichtgewichtig: ein Python-HTTP-Server (aiohttp) liefert eine einzelne Seite mit eingebettetem JS und Diagrammen, ohne Build-Schritt. Funktioniert in der HA-Seitenleiste, auf Mobil und im Dunkelmodus.

**Seiten**

1. **Übersicht** – aktueller Modus (Laden / Halten / Versorgen / Normalbetrieb) mit Begründung in einem Satz, Akkustand, aktuelle Leistung, Plan-Gültigkeit, Betriebsstufe, Zustand der Schutzbedingungen, Ampel für Datenqualität.
2. **Plan** – Zeitleiste der nächsten 24–72 h: Preiskurve, Modusbänder, erwarteter Akkustand, PV- und Verbrauchsprognose, bekannte vs. geschätzte Preise getrennt gefärbt. Ein Fenster antippen zeigt die Begründung („Laden, weil … ct/kWh unter Schwelle … ct, spart … €“).
3. **Wirkung** – gemessene Ersparnis (Wochenbilanz), Wirkungsgrad-Messung, Prognosegüte (Soll/Ist), Vergleich mit „Wechselrichter dauernd an“.
4. **Protokoll** – jeder Lauf: wann, Ergebnis, Planänderung ja/nein, Fehler im Klartext, was in HA geschrieben wurde.
5. **Einstellungen** – Assistent für Geräte-Zuordnung mit Live-Prüfung, Tarif- und Akku-Werte, Standort, Betriebsstufe, Benachrichtigung. Änderungen werden validiert und als Diff gezeigt, bevor sie gelten.
6. **Steuerung** – Vorschau der generierten Automation, Freigabe an/aus, Not-Aus „Plan sofort ungültig“.

**Schnittstelle** (`/api/…`, nur von Ingress erreichbar): `status`, `plan`, `history`, `runs`, `config` (GET/PUT mit Validierung), `entities/suggest`, `entities/check`, `run` (POST), `control/preview|install|enable|panic`.

## Verzeichnisaufbau

```
repository.yaml
hausakku_planer/            # das Add-on
  config.yaml  Dockerfile  run.sh  DOCS.md  CHANGELOG.md  icon.png
  app/                      # Python-Paket (Kern + ha/ + prices/ + web/)
tests/                      # Python-Tests, laufen ohne HA
docs/
```

## Meilensteine

| # | Inhalt | Ergebnis |
|---|---|---|
| M0 | Kopie, Struktur, Tests grün (263) | **erledigt** |
| M1 | Add-on-Gerüst + `paths.py` + Optionen + Dienst-Schleife | **erledigt** (Container-Build noch nicht getestet) |
| M2 | Native HA-Schicht + Konfiguration der Entitäten; Scheduler; `observe` rechnet echten Plan | **Code und Tests fertig (281 grün), Test gegen echtes HA steht aus** |
| M3 | Ingress-UI: Übersicht, Plan, Protokoll (+ Einstellungen mit Entitäts-Prüfung) | **Code und Tests fertig, im Browser mit Demo-Daten geprüft** |
| M4 | Einrichtungsassistent (Vorschläge sind in M3 schon da), Preisanbieter-Abstraktion, neutrale Defaults | Dritte können konfigurieren |
| M5 | `publish`: Helfer und Zeitpläne anlegen/schreiben mit Readback | Paralleltest neben dem Original |
| M6 | Generierter Guard + Steuer-Automation (`control`) | Umstieg möglich |
| M7 | Doku, Übersetzungen, Icon, Release-Pipeline, öffentliches Repository | Weitergabe |

## Offene Risiken

- **Tibber-Antwortformat** und `return_response` über REST sind zu prüfen; Anbieter-Schnittstelle fängt Unterschiede ab.
- **Statistik-Verfügbarkeit:** Fremdanlagen haben evtl. weniger als 28 Tage Verlauf; der Assistent muss einen Kaltstart mit Platzhalterprofilen ermöglichen und ehrlich anzeigen, wie belastbar der Plan ist.
- **Hardware-Vielfalt:** Das Modell kennt Laden, Halten, Versorgen über zwei Schalter. Andere Systeme (Hybridwechselrichter mit Betriebsmodus-Select) brauchen später eine Aktions-Abstraktion.
- **Eigene Messwerte** (Wirkungsgrad, Ladeleistung) hängen an sauberen Zählern; Plausibilitätsprüfung im Assistenten.

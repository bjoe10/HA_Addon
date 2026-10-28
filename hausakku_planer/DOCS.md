# Hausakku-Planer

Plant für einen Heimspeicher mit dynamischem Stromtarif, **wann er aus dem Netz laden, Energie aufheben oder das Haus versorgen soll**. Grundlage sind die Börsen- oder Tibber-Preise der nächsten ein bis zwei Tage, die PV-Prognose und dein gelernter Verbrauch. Daraus entsteht ein Plan, den eine Home-Assistant-Automation ausführt.

> **Wichtig:** Die Berechnung ist eine Simulation. Es gibt keine Garantie für Ersparnisse, und die Steuerung ersetzt weder ein BMS noch elektrische Schutzeinrichtungen. Nutzung auf eigene Verantwortung. Fang mit der Stufe **Beobachten** an.

## Was du brauchst

- Einen Speicher, dessen **Netzladegerät** und **Wechselrichter** je über einen Schalter in Home Assistant (`switch`) ein- und ausgeschaltet werden können. Das Modell kennt drei Zustände: Netzladen (Ladegerät an, Wechselrichter aus), Aufheben (beide aus, PV lädt weiter) und Versorgen (Wechselrichter an).
- Einen **dynamischen Stromtarif**: die Tibber-Integration, einen Sensor mit Preisliste im Attribut (Nordpool, EPEX Spot und ähnliche) oder den Börsenpreis von energy-charts mit Aufschlag und MwSt. Preise im 15- oder 60-Minuten-Raster.
- **kWh-Zähler** mit Langzeitstatistik (`state_class` `total` oder `total_increasing`) für Netzbezug, Einspeisung, PV, Wechselrichter-Ausgang und Netzladegerät.
- Den **Akku-Ladestand** in Prozent.
- Mindestens ein paar Tage Statistik, besser 28 Tage, damit der Verbrauch gelernt werden kann.

Die Zeitzone ist fest Europa/Berlin. Preiszonen außerhalb von Mitteleuropa sind ungetestet.

## Einrichtung in sechs Schritten

1. **Add-on installieren und starten.** Unter Einstellungen → Add-ons → Add-on-Store → ⋮ → Repositories die Adresse `https://github.com/bjoe10/HA_Addon` hinzufügen, „Hausakku-Planer“ installieren, starten und „In Seitenleiste anzeigen“ aktivieren.
2. **„Hausakku“ in der Seitenleiste öffnen → Einstellungen.** Die Entitäten zuordnen. Das Feld schlägt passende Entitäten vor, **Prüfen** zeigt, ob der Zähler existiert, die richtige Einheit hat und genug Statistik liefert.
3. **Standort, Akku-Kapazität und Leistungen eintragen.** Der Standort (auf ca. 1 km gerundet) macht die PV-Schätzung genauer. Ladeleistung des Netzladegeräts und maximale Wechselrichter-Leistung bestimmen, wie viel pro Stunde möglich ist.
4. **Strompreis wählen** und mit **Preise prüfen** kontrollieren. Der Plan nutzt nur bekannte Preise, die für morgen liegen meist ab dem frühen Nachmittag vor.
5. **Speichern und „Jetzt rechnen“** auf der Übersicht. Der erste Lauf braucht etwa eine Minute. Danach rechnet das Add-on selbst: 14:15 und 20:15 ein Hauptlauf, stündlich um :45 eine stille Nachplanung, montags 08:00 die Wochenbilanz.
6. **Plan beobachten.** Unter „Plan“ siehst du Preise, Modus-Bänder, Akkustand und zu jedem Fenster eine Begründung in einem Satz. Mehrere Tage reichen, um zu sehen, ob die Entscheidungen zu deinem Haus passen.

## Betriebsstufen (Add-on-Konfiguration)

| Stufe | Wirkung |
|---|---|
| **Beobachten** (`observe`, Standard) | Rechnet und zeigt den Plan. Schreibt **nichts** in Home Assistant. |
| **Plan veröffentlichen** (`publish`) | Schreibt den Plan zusätzlich in eigene Helfer in Home Assistant (siehe unten) und legt diese an, falls sie fehlen. Schaltet nichts. |

**Das Add-on schaltet in keiner Stufe selbst Geräte.** Das macht eine Automation aus dem Blueprint (nächster Abschnitt). Fällt das Add-on aus, läuft der zuletzt veröffentlichte Plan bis zu seinem Ablaufzeitpunkt weiter, danach greift der sichere Rückfall (nur Wechselrichter, kein Netzladen).

### Eigene Helfer

Mit der Stufe „Plan veröffentlichen“ legt das Add-on diese Helfer an, mit dem Präfix aus Einstellungen → Eigene Helfer (Standard `hap`):

| Helfer | Zweck |
|---|---|
| `schedule.hap_netzladen` und `schedule.hap_entladen` | Fenster für Netzladen und Versorgen, tagesgenau mit `plan_date` |
| `input_datetime.hap_plan_gueltig_bis` | Ablaufzeitpunkt des Plans |
| `input_number.hap_ziel_soc` | Ladeziel in % |
| `input_text.hap_plan_status` | Kurzstatus |
| `input_boolean.hap_planer_freigabe` | **Freigabe**, immer aus beim Anlegen, wird vom Add-on nie eingeschaltet |
| `input_boolean.hap_regler_uebernommen` | Merker der Steuerung |
| `timer.hap_schaltsperre` | Schaltsperre |
| `sensor.hap_bericht` | Bericht und Faktenblock der letzten Läufe (für Zusammenfassungen) |

Das Add-on schreibt nur in diese Helfer. Gerätezustände oder Schalter fasst es nicht an.

## Steuerung: der Blueprint

Der Blueprint **„Hausakku-Planer Steuerung“** führt den Plan aus. Er schaltet Ladegerät und Wechselrichter nach den Zeitplänen, mit diesen Sicherungen:

- Solange die **Freigabe aus** ist, wird nichts geschaltet.
- Der Plan wirkt nur bis zu seinem Ablaufzeitpunkt und nur an dem Tag, für den er eingetragen ist.
- Ladegerät und Wechselrichter laufen **nie gleichzeitig**: Vor dem Einschalten wird das Gegenstück bestätigt ausgeschaltet, 2 Sekunden gewartet und alles noch einmal geprüft.
- **Schutzstopps und Ladeende** schalten sofort ab, ein erneutes Einschalten wartet die **Schaltsperre** (Standard 5 Minuten) ab.
- Reserve (Standard: unter 10 % nicht mehr entladen, wieder ab 12 %), Obergrenze fürs Netzladen (Standard 90 %).
- Unbekannte, nicht numerische oder unplausible Werte schalten beide Geräte ab.
- Optional, wenn du die Sensoren zuordnest: Spannung, Temperaturen, BMS online und Herzschlag, Lade- und Entlade-Freigabe des BMS, eine externe Entladesperre.

### Einrichten

1. In **Einstellungen → Steuerung (Blueprint)** den Link „Blueprint importieren“ öffnen (oder die Datei `blueprints/automation/hausakku_planer/steuerung.yaml` aus dem Repository importieren).
2. In Home Assistant **Einstellungen → Automationen → Neue Automation → Blueprint „Hausakku-Planer Steuerung“**. Die Einstellungsseite des Add-ons listet genau die Werte, die du wählen musst.
3. Die optionalen Schutzwerte unter „Batterie-Schutz“ ausfüllen, soweit du die Sensoren hast. Je mehr, desto besser der Schutz.
4. Automation speichern. Erst **nach ein paar Tagen Beobachten** den Schalter `input_boolean.<Präfix>_planer_freigabe` einschalten, und die ersten Schaltungen selbst begleiten.
5. Zum Stoppen: Freigabe aus. Die Steuerung gibt dann nur Geräte frei, die sie vorher selbst übernommen hatte.

**Bekannte Grenzen:** Spannungs-, Temperatur- und BMS-Schutz greifen innerhalb einer Minute (Minutenlauf), nicht in derselben Sekunde. Das BMS muss seine Schutzfunktionen selbst übernehmen. Hybridwechselrichter mit Betriebsmodus statt Schaltern werden nicht unterstützt.

## Preisquellen

- **Tibber:** Dienst `tibber.get_prices` der HA-Integration. Bei mehreren Zuhause eines wählen.
- **Sensor in Home Assistant:** Ein Sensor mit Preisliste im Attribut (Nordpool, EPEX Spot, …). Das Add-on erkennt die Listen und die Einheit (EUR/kWh, ct/kWh, EUR/MWh). Aufschlag (ct netto) und MwSt. kannst du ergänzen.
- **Börsenpreis:** Day-ahead-Preis von energy-charts je Gebotszone (Standard DE-LU), plus Aufschlag und MwSt.

Stundenpreise werden auf Viertelstunden erweitert. Raster mit 30 Minuten werden abgelehnt. Lücken füllt das Add-on nie: Ohne bekannte Preise gibt es keine Schaltfenster.

## Bericht-Sensor und Zusammenfassungen

Ab „Plan veröffentlichen“ liegt nach jedem Lauf ein Bericht in `sensor.<Präfix>_bericht` (Attribute `main`, `replan`, `weekly`). Ein Assistent oder eine andere Automation kann ihn lesen und zusammenfassen, ohne selbst etwas zu rechnen. Der Sensor wird mit dem nächsten Lauf neu geschrieben, wenn Home Assistant neu startet.

## Wochenbilanz

Montags 08:00 rechnet das Add-on nach, was die Steuerung in der letzten Woche tatsächlich gebracht hat, gemessen an deinen Zählern und den Preisen, im Vergleich zu „Wechselrichter dauernd an“. Sie braucht Preise für die ganze Woche. Auf einer neuen Installation entsteht der Preisverlauf erst nach und nach, die Bilanz deckt dann den Zeitraum ab, für den es lückenlose Daten gibt (mindestens 24 Stunden).

## Fehlersuche

| Meldung oder Beobachtung | Ursache und Abhilfe |
|---|---|
| „Einrichtung unvollständig“ | Pflichtfelder in den Einstellungen fehlen. Die Meldung nennt sie. |
| Prüfen meldet „keine Statistik“ | Der Zähler hat keine `state_class`, oder Home Assistant kennt ihn nicht lange genug. Nur `total` und `total_increasing` zählen. |
| Plan „Schatten“ | Der Freigabe-Schalter existiert nicht oder ist aus. Das Add-on veröffentlicht trotzdem. |
| Wächter zeigt `sicher_aus` | Ein Wert ist unbekannt oder unplausibel, beide Geräte sind aus. Die Automationsspur zeigt, welche. |
| Preise fehlen | „Preise prüfen“ zeigt Zeitraum, Lücken und aktuellen Preis. Tibber liefert die Preise für morgen erst am Nachmittag. |
| Plan abgelaufen | Das Add-on läuft nicht oder hat nach dem Ablaufzeitpunkt keinen Lauf geschafft. Dann gilt der Rückfall (nur Wechselrichter). |

## Datenschutz

Das Add-on arbeitet lokal. Nach außen gehen nur die Abfragen von Open-Meteo (Strahlungsprognose, mit dem gerundeten Standort) und, falls gewählt, von energy-charts (Börsenpreise). Persönliche Daten verlassen Home Assistant nicht.

## Lokale Installation zum Testen

Ordner `hausakku_planer` auf den HA-Rechner nach `/addons/hausakku_planer` kopieren (Samba-Freigabe „addons“ oder SSH),
dann unter Einstellungen → Add-ons → Add-on-Store → ⋮ → „Nach Updates suchen“ und „Hausakku-Planer“ unter „Lokale Add-ons“ installieren.

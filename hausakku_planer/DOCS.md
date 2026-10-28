# Hausakku-Planer

Plant, wann ein Heimspeicher laden, halten oder das Haus versorgen soll, anhand dynamischer Strompreise,
PV- und Verbrauchsprognose.

## Erster Start

1. Add-on starten und **„Hausakku“ in der Seitenleiste** öffnen.
2. Unter **Einstellungen** die Entitäten zuordnen und mit **Prüfen** kontrollieren (Zähler brauchen Langzeitstatistik, also `state_class` `total` oder `total_increasing`). Standort und Akku-Kapazität eintragen.
3. Nach dem Speichern rechnet das Add-on beim nächsten Zeitpunkt (14:15, 20:15, stündlich :45) oder sofort über **Jetzt rechnen** auf der Übersicht.

## Betriebsstufen (Add-on-Konfiguration)

| Stufe | Wirkung |
|---|---|
| `observe` (Standard) | Rechnet und zeigt den Plan. Schreibt **nichts** in Home Assistant. |
| `publish` | Schreibt den Plan in eigene Helfer (`schedule.hausakku_*`, `input_*.hausakku_*`). Schaltet nichts. |
| `control` | Reserviert für die Steuer-Automation (noch nicht verfügbar). |

Das Add-on schaltet in keiner Stufe selbst Geräte.

## Voraussetzungen

- Tibber-Integration in Home Assistant (Viertelstundenpreise über `tibber.get_prices`); weitere Preisquellen folgen.
- Zähler für Netzbezug, Einspeisung, PV, Wechselrichter-Ausgang und Netzladegerät (kWh, mit Langzeitstatistik).
- Akku-Ladestand in %.
- Zeitzone und Preislogik sind derzeit auf Deutschland ausgelegt.

## Lokale Installation zum Testen

Ordner `hausakku_planer` auf den HA-Rechner nach `/addons/hausakku_planer` kopieren (Samba-Freigabe „addons“ oder SSH),
dann unter Einstellungen → Add-ons → Add-on-Store → ⋮ → „Nach Updates suchen“ und „Hausakku-Planer“ unter „Lokale Add-ons“ installieren.

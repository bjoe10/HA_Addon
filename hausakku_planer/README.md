# Hausakku-Planer

Plant Laden, Halten und Versorgen eines Heimspeichers nach dynamischen Strompreisen
(Tibber, Nordpool und andere Preisquellen, PV- und Verbrauchsprognose, Mehrtagessicht), mit Weboberfläche in der HA-Seitenleiste
und einem Blueprint, der den Plan sicher ausführt.

- **Beobachten zuerst:** Die Standardstufe schreibt nichts in Home Assistant.
- **Das Add-on schaltet nie selbst.** Die Steuerung ist eine Automation aus dem mitgelieferten Blueprint, mit Freigabe-Schalter, Ablaufdatum, Schaltsperre und Schutzbedingungen.
- Schritt-für-Schritt-Einrichtung, Sicherungen und Fehlersuche: [DOCS.md](DOCS.md). Änderungen: [CHANGELOG.md](CHANGELOG.md). Architektur: [dev/docs/ARCHITECTURE.md](dev/docs/ARCHITECTURE.md). Tests: `dev/run_tests.sh`. Lizenz: MIT.

Die Berechnung ist eine Simulation; es gibt keine Garantie für Ersparnisse. Nutzung auf eigene Verantwortung.

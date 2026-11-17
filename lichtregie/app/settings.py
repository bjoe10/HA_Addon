"""Einstellungen aus der Oberfläche. Sie überdauern einen Neustart (DATA/settings.json)."""

import config
import jsonfile

SETTINGS = {
    # Party-Modus: automatisch an, wenn Musik ankommt; aus nach so vielen Minuten ohne Musik
    "automatik": True, "party_aus_min": 15,
    # Show
    "strobe": True, "strobe_menge": 100, "nebel": False, "tempo": 2.0,        # tempo = Bewegungstempo ×1/×2
    "offset": 0.0,                                       # Phasen-Versatz in Schlägen (ohne Audio)
    # Mechanik der Köpfe (gemessen, siehe SHOW.md)
    "vorlauf": 0.4,                                      # Bewegung so viele Sekunden vorziehen
    "anschub": True, "vorsteuerung": 0.45,
    # Live-Audio
    # Ton-Vorlauf: Der Empfänger (shairport-sync, stdout) liefert den Ton ca. 1,0 s bevor der Lautsprecher ihn
    # spielt (Puffer 1 s; gemessen 15.11.2026 mit Aufnahmen und Beat This!). Die Show hängt so weit zurück.
    "audio": True, "ton_vorlauf": 1.0, "takttest": False,
    "beatthis": True,                                    # „1“ im Takt mit Beat This (downbeat.py)
    # Lampen über HA
    "lampen": True, "lampen_decke": 40, "lampen_vitrine": 100, "lampen_vorlauf": 0.8,
    # Ambilights: Farbwechsel alle so viele Schläge (0 = nach dem Lied: 8 oder 16 Takte; mindestens ein Takt),
    # hart (ohne Übergang); Lampen-Test zum Einstellen des Vorlaufs
    "lampen_wechsel": 8.0, "lampen_hart": True, "lampentest": False,
    # Laser: Senden an/aus, Schutzgrenzen, Ruhepunkt über dem TV (auf dem TV sieht man ihn schlecht)
    "laser": True, "laser_ud_min": 42, "laser_ud_max": 86, "laser_lr_min": 39, "laser_lr_max": 90,
    "laser_ud_mitte": 76,
}
FILE = config.DATA / "settings.json"
_saved = jsonfile.load(FILE)
SETTINGS.update(_saved)
SETTINGS["takttest"] = False   # Takt-Test und Lampen-Test starten nie von selbst
SETTINGS["lampentest"] = False
for _old in ("lampen_dunkel", "audio_versatz"):   # entfernte Einstellungen
    SETTINGS.pop(_old, None)

# Erlaubte Werte je Einstellung: bool oder (Typ, min, max)
RULES = {
    "beatthis": bool, "strobe": bool, "nebel": bool, "anschub": bool, "lampen": bool, "audio": bool, "takttest": bool,
    "laser": bool, "automatik": bool, "party_aus_min": (int, 1, 240),
    "lampen_hart": bool, "lampentest": bool, "lampen_wechsel": (float, 0.0, 64.0),
    "strobe_menge": (int, 0, 200),
    "offset": (float, -64.0, 64.0), "tempo": (float, 0.25, 4.0), "vorsteuerung": (float, 0.0, 1.0),
    "ton_vorlauf": (float, 0.0, 3.0), "lampen_vorlauf": (float, 0.0, 2.0),
    "lampen_decke": (int, 0, 150), "lampen_vitrine": (int, 0, 150),
    "laser_ud_min": (int, 0, 255), "laser_ud_max": (int, 0, 255), "laser_lr_min": (int, 0, 255),
    "laser_lr_max": (int, 0, 255), "laser_ud_mitte": (int, 0, 255),
}


def save():
    jsonfile.save(FILE, SETTINGS)


def update(body):
    """Übernimmt bekannte Einstellungen aus einer Anfrage (geprüft und begrenzt) und speichert.
    Gibt die Namen der geänderten Einstellungen zurück."""
    changed = []
    for key, rule in RULES.items():
        if key not in body:
            continue
        if rule is bool:
            value = bool(body[key])
        else:
            kind, lo, hi = rule
            value = max(lo, min(hi, kind(float(body[key]))))
            if kind is float:
                value = round(value, 3)
        SETTINGS[key] = value
        changed.append(key)
    save()
    return changed
